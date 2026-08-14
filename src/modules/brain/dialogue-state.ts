import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { brainMemoryFacts, dialogueStates } from "../../db/schema.js";
import type { AssistantMessageBlock } from "../chat/message-blocks.js";
import type { AgentToolResult } from "./tool-registry.js";
import { resolveCanonicalMemoryKey } from "./memory-key-policy.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import { isCognitiveFoundationEnabled } from "./cognitive-foundation-policy.js";

const uuidSchema = z.string().uuid();

const DIALOGUE_STATE_CACHE_TTL_MS = 750;
/**
 * Dialogue state is working memory. Durable facts, episodes, and goals remain
 * available through the cognitive memory layer, while stale turn-local loops
 * should not resurrect themselves after a long inactive period.
 */
export const DIALOGUE_WORKING_MEMORY_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const DIALOGUE_STATE_CACHE_MAX_ENTRIES = 4_096;
const RELATIONSHIP_DEPTH_CACHE_TTL_MS = 5_000;
const RELATIONSHIP_DEPTH_CACHE_MAX_ENTRIES = 4_096;

export function isDialogueStateFresh(
  updatedAt: Date | string | null | undefined,
  now = new Date(),
): boolean {
  if (updatedAt == null || updatedAt === "") {
    // Keep rows written before the freshness field was consumed compatible.
    return true;
  }
  const parsed = updatedAt instanceof Date ? updatedAt : new Date(updatedAt);
  if (!Number.isFinite(parsed.getTime())) {
    return false;
  }
  return now.getTime() - parsed.getTime() <= DIALOGUE_WORKING_MEMORY_TTL_MS;
}

type DialogueStateCacheEntry = {
  value: DialogueStateSnapshot | null;
  expiresAt: number;
  pending?: Promise<DialogueStateSnapshot | null>;
};

type RelationshipDepthCacheEntry = {
  value: number;
  expiresAt: number;
  pending?: Promise<number>;
};

const dialogueStateCache = new WeakMap<
  FastifyInstance,
  Map<string, DialogueStateCacheEntry>
>();
const relationshipDepthCache = new WeakMap<
  FastifyInstance,
  Map<string, RelationshipDepthCacheEntry>
>();

function dialogueStateCacheKey(userId: string, sessionId: string): string {
  return `${userId}:${sessionId}`;
}

function boundedCacheInsert<T>(
  cache: Map<string, T>,
  key: string,
  value: T,
  maxEntries: number,
): void {
  if (!cache.has(key) && cache.size >= maxEntries) {
    const oldestKey = cache.keys().next().value as string | undefined;
    if (oldestKey) cache.delete(oldestKey);
  }
  cache.set(key, value);
}

const styleSignatureSchema = z
  .object({
    opener: z.string().trim().max(120).nullable().default(null),
    closer: z.string().trim().max(120).nullable().default(null),
  })
  .default({});

const toolHistoryItemSchema = z.object({
  tool: z.string().trim().min(1).max(120),
  at: z.string().datetime({ offset: true }),
  status: z.enum(["requested", "completed", "failed"]).default("requested"),
  durationMs: z.number().int().nonnegative().optional(),
  errorCode: z.string().trim().max(120).nullable().optional(),
});

const moodTrendItemSchema = z.object({
  mood: z.string().trim().max(160),
  energy: z.enum(["low", "mid", "high"]).default("mid"),
  at: z.string().datetime({ offset: true }),
});

const conversationDynamicsSchema = z.object({
  turnCount: z.number().int().nonnegative().default(0),
  averageReplyChars: z.number().nonnegative().default(0),
  recentOpeners: z.array(z.string().max(120)).max(6).default([]),
  recentClosers: z.array(z.string().max(120)).max(6).default([]),
}).default({});

const userMemorySchema = z.object({
  name: z.string().trim().max(120).nullable().default(null),
  preferredName: z.string().trim().max(120).nullable().default(null),
  preferredLanguage: z.string().trim().max(80).nullable().default(null),
  preferredTone: z.string().trim().max(120).nullable().default(null),
  responseStyle: z.string().trim().max(160).nullable().default(null),
  timezone: z.string().trim().max(80).nullable().default(null),
  updatedAt: z.string().datetime({ offset: true }).nullable().default(null),
}).default({});

const memoryRefsSchema = z.object({
  revision: z.number().int().nonnegative().default(0),
  factIds: z.array(z.string().uuid()).max(80).default([]),
  episodeIds: z.array(z.string().uuid()).max(40).default([]),
}).default({});

const turnTraceSchema = z.object({
  at: z.string().datetime({ offset: true }).nullable().default(null),
  user: z.string().trim().min(1).max(280),
  assistant: z.string().trim().min(1).max(320).nullable().default(null),
  workload: z.string().trim().max(80).nullable().default(null),
});

const turnSalienceSchema = z.object({
  topics: z.array(z.string().trim().min(2).max(80)).max(8).default([]),
  entities: z.array(z.string().trim().min(2).max(80)).max(10).default([]),
  userIntent: z.string().trim().max(160).nullable().default(null),
  assistantCommitment: z.string().trim().max(160).nullable().default(null),
  emotionalTone: z.string().trim().max(80).nullable().default(null),
  referenceMode: z.enum(["none", "continue", "revise", "resolve_pronoun"]).default("none"),
  referentCandidates: z.array(z.string().trim().min(2).max(120)).max(8).default([]),
  unresolved: z.boolean().default(false),
  updatedAt: z.string().datetime({ offset: true }).nullable().default(null),
}).default({});

export const dialogueStateSchema = z
  .object({
    goal: z.string().trim().max(500).nullable().default(null),
    stage: z.string().trim().max(240).nullable().default(null),
    openLoops: z.array(z.string().trim().min(1).max(500)).max(12).default([]),
    lastAssistantDigest: z.string().trim().max(500).nullable().default(null),
    styleSignature: styleSignatureSchema,
    userRegister: z.string().trim().max(160).nullable().default(null),
    factsTouched: z.array(z.string().trim().min(1).max(160)).max(80).default([]),
    toolHistory: z.array(toolHistoryItemSchema).max(40).default([]),
    moodTrend: z.array(moodTrendItemSchema).max(20).default([]),
    lastProactiveAt: z.string().datetime({ offset: true }).nullable().default(null),
    conversationDynamics: conversationDynamicsSchema,
    turns: z.array(turnTraceSchema).max(12).default([]),
    salience: turnSalienceSchema,
    userMemory: userMemorySchema,
    memoryRefs: memoryRefsSchema,
  })
  .default({});

export type DialogueState = z.output<typeof dialogueStateSchema>;

export type DialogueStateSnapshot = {
  sessionId: string;
  userId: string;
  revision: number;
  state: DialogueState;
  updatedAt?: Date;
};

export type DialogueStateTurnInput = {
  userId: string;
  sessionId: string | null;
  requestMetadata?: Record<string, unknown>;
  userMessage: string;
  assistantText: string;
  assistantBlocks?: AssistantMessageBlock[];
  envelope?: TurnEnvelope | null;
  toolResults?: AgentToolResult[];
  workload?: string | null;
  memoryRefs?: { revision: number; factIds?: string[]; episodeIds?: string[] };
};

type DialogueDb = FastifyInstance["db"];

const DIALOGUE_STATE_METADATA_SOURCE = "server_dialogue_state.v1";

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function clip(value: string, max: number): string {
  const trimmed = value.trim().replace(/\s+/g, " ");
  return trimmed.length > max ? `${trimmed.slice(0, Math.max(0, max - 1))}…` : trimmed;
}

function appendUnique(values: string[], additions: string[], max: number): string[] {
  const output: string[] = [];
  for (const value of [...additions, ...values]) {
    const clipped = clip(value, 500);
    if (clipped && !output.includes(clipped)) {
      output.push(clipped);
    }
    if (output.length >= max) {
      break;
    }
  }
  return output;
}

function scrubPrivateSnippet(value: string, max = 160): string {
  return clip(value, max)
    .replace(/https?:\/\/\S+/gi, "[url]")
    .replace(/(?:\/Users\/|\/home\/|C:\\Users\\)[^\s]+/gi, "[path]")
    .replace(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g, "[email]")
    .replace(/\b(?:\+?\d[\d\s().-]{7,}\d)\b/g, "[number]");
}

function scrubOptionalSnippet(value: unknown, max: number): string | null {
  const text = readString(value);
  return text ? scrubPrivateSnippet(text, max) : null;
}

function sanitizeTurnTrace(value: unknown): z.output<typeof turnTraceSchema> | null {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const user = scrubOptionalSnippet(record.user, 280);
  if (!user) {
    return null;
  }
  return turnTraceSchema.parse({
    at: readString(record.at),
    user,
    assistant: scrubOptionalSnippet(record.assistant, 320),
    workload: scrubOptionalSnippet(record.workload, 80),
  });
}

function sanitizeTurnTraces(value: unknown): z.output<typeof turnTraceSchema>[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map(sanitizeTurnTrace)
    .filter((item): item is z.output<typeof turnTraceSchema> => item != null)
    .slice(0, 12);
}

function sanitizeSalience(value: unknown): DialogueState["salience"] {
  const record = readRecord(value);
  if (!record) {
    return turnSalienceSchema.parse({});
  }
  const topics = Array.isArray(record.topics)
    ? record.topics.map(String).map((item) => scrubPrivateSnippet(item, 80)).filter(Boolean).slice(0, 8)
    : [];
  const entities = Array.isArray(record.entities)
    ? record.entities.map(String).map((item) => scrubPrivateSnippet(item, 80)).filter(Boolean).slice(0, 10)
    : [];
  const referenceMode = readString(record.referenceMode);
  return turnSalienceSchema.parse({
    topics,
    entities,
    userIntent: scrubOptionalSnippet(record.userIntent, 160),
    assistantCommitment: scrubOptionalSnippet(record.assistantCommitment, 160),
    emotionalTone: scrubOptionalSnippet(record.emotionalTone, 80),
    referenceMode: ["continue", "revise", "resolve_pronoun"].includes(referenceMode ?? "")
      ? referenceMode
      : "none",
    referentCandidates: Array.isArray(record.referentCandidates)
      ? record.referentCandidates
          .map(String)
          .map((item) => scrubPrivateSnippet(item, 120))
          .filter(Boolean)
          .slice(0, 8)
      : [],
    unresolved: typeof record.unresolved === "boolean" ? record.unresolved : false,
    updatedAt: readString(record.updatedAt),
  });
}

function sanitizeDialogueStateSnapshot(state: DialogueState): DialogueState {
  return dialogueStateSchema.parse({
    ...state,
    goal: state.goal ? scrubPrivateSnippet(state.goal, 500) : null,
    stage: state.stage ? scrubPrivateSnippet(state.stage, 240) : null,
    openLoops: state.openLoops.map((item) => scrubPrivateSnippet(item, 500)).filter(Boolean).slice(0, 12),
    lastAssistantDigest: state.lastAssistantDigest
      ? scrubPrivateSnippet(state.lastAssistantDigest, 500)
      : null,
    factsTouched: state.factsTouched.map((item) => scrubPrivateSnippet(item, 160)).filter(Boolean).slice(0, 80),
    turns: sanitizeTurnTraces(state.turns),
    salience: sanitizeSalience(state.salience),
  });
}

function normalizeSearchToken(value: string): string {
  return value
    .toLocaleLowerCase("tr")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ı/g, "i")
    .replace(/ç/g, "c")
    .replace(/ğ/g, "g")
    .replace(/ö/g, "o")
    .replace(/ş/g, "s")
    .replace(/ü/g, "u")
    .replace(/[^a-z0-9_.:-]+/g, " ")
    .trim();
}

const SALIENCE_STOP_WORDS = new Set([
  "bana", "bunu", "şunu", "sunu", "buna", "gore", "göre", "icin", "için",
  "daha", "biraz", "sonra", "onceki", "önceki", "aynı", "ayni", "şekilde",
  "sekilde", "devam", "nasıl", "nasil", "nedir", "what", "this", "that",
  "with", "from", "into", "about", "please", "the", "and", "bir", "ve",
]);

function extractSalienceTopics(text: string): string[] {
  const normalized = normalizeSearchToken(text);
  const output: string[] = [];
  for (const token of normalized.split(/\s+/)) {
    if (
      token.length < 4 ||
      token.length > 36 ||
      SALIENCE_STOP_WORDS.has(token) ||
      /^\d+$/.test(token)
    ) {
      continue;
    }
    if (!output.includes(token)) {
      output.push(token);
    }
    if (output.length >= 8) {
      break;
    }
  }
  return output;
}

function extractSalienceEntities(text: string): string[] {
  const compact = scrubPrivateSnippet(text, 600);
  const candidates = compact.match(/\b[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü0-9_.-]{2,}(?:\s+[A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşü0-9_.-]{2,}){0,2}\b/g) ?? [];
  const tech = compact.match(/\b(?:API|URL|JSON|SSE|Redis|Postgres|Fastify|Flutter|TypeScript|Python|Docker|OAuth|JWT|WebSocket|MCP)\b/g) ?? [];
  return appendUnique([], [...tech, ...candidates], 10).map((item) => clip(item, 80));
}

function deriveUserIntentSnippet(message: string): string | null {
  const cleaned = scrubPrivateSnippet(message, 160);
  if (!cleaned) {
    return null;
  }
  const firstSentence = cleaned.split(/(?<=[.!?])\s+/)[0] ?? cleaned;
  return firstSentence ? clip(firstSentence, 160) : null;
}

function deriveAssistantCommitment(text: string): string | null {
  const cleaned = scrubPrivateSnippet(text, 240);
  if (!cleaned) {
    return null;
  }
  const sentence = cleaned
    .split(/(?<=[.!?])\s+/)
    .find((part) =>
      /\b(yapacağım|yapacagim|bakacağım|bakacagim|devam edeceğim|edecegim|hazırlayacağım|hazirlayacagim|kontrol edeceğim|hatırlatacağım|hatirlatacagim|edecegim|I will|I'll|next|sonraki|devam)\b/i.test(part),
    );
  return sentence ? clip(sentence, 160) : null;
}

function deriveReferenceContext(
  previous: DialogueState["salience"],
  userMessage: string,
): Pick<DialogueState["salience"], "referenceMode" | "referentCandidates"> {
  const compactUserMessage = normalizeSearchToken(userMessage.replace(/\s+/g, " "));
  const referenceMode = /^(?:devam|devam et|surdur|continue|go on|keep going)\b/u.test(compactUserMessage)
    ? "continue"
    : /^(?:bunu|sunu|onu|boyle|aynisini|that|this|it)\b.{0,80}(?:duzelt|degistir|yeniden|revise|fix|change)/u.test(compactUserMessage)
      ? "revise"
      : /^(?:bunu|sunu|onu|bu|su|o|ikincisini|birincisini|sonuncusunu|that|this|it|the second|the first)\b/u.test(compactUserMessage)
        ? "resolve_pronoun"
        : "none";
  const referentCandidates = referenceMode === "none"
    ? []
    : appendUnique([], [
        ...previous.entities,
        ...previous.topics,
        previous.assistantCommitment ?? "",
        previous.userIntent ?? "",
      ], 8).map((item) => clip(item, 120));
  return { referenceMode, referentCandidates };
}

function deriveTurnSalience(input: {
  previous: DialogueState["salience"];
  userMessage: string;
  assistantText: string;
  envelope?: TurnEnvelope | null;
  newLoops: string[];
  toolResults: AgentToolResult[];
  nowIso: string;
}): DialogueState["salience"] {
  const previous = turnSalienceSchema.parse(input.previous ?? {});
  const { referenceMode, referentCandidates } = deriveReferenceContext(
    previous,
    input.userMessage,
  );
  const topics = appendUnique(
    previous.topics,
    extractSalienceTopics(`${input.userMessage} ${input.assistantText}`),
    8,
  );
  const entities = appendUnique(
    previous.entities,
    extractSalienceEntities(`${input.userMessage} ${input.assistantText}`),
    10,
  );
  const userIntent = deriveUserIntentSnippet(input.userMessage) ?? previous.userIntent;
  const assistantCommitment = deriveAssistantCommitment(input.assistantText) ?? previous.assistantCommitment;
  const emotionalTone =
    input.envelope?.affect.user_mood_guess ??
    previous.emotionalTone ??
    null;
  const unresolved =
    input.newLoops.length > 0 ||
    input.toolResults.some((result) => !result.ok) ||
    /\?$/.test(input.userMessage.trim());
  return turnSalienceSchema.parse({
    topics,
    entities,
    userIntent,
    assistantCommitment,
    emotionalTone,
    referenceMode,
    referentCandidates,
    unresolved,
    updatedAt: input.nowIso,
  });
}

function normalizeMemoryKey(value: string): string {
  return value
    .trim()
    .toLocaleLowerCase("tr")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ı/g, "i")
    .replace(/ç/g, "c")
    .replace(/ğ/g, "g")
    .replace(/ö/g, "o")
    .replace(/ş/g, "s")
    .replace(/ü/g, "u")
    .replace(/[^a-z0-9_.:-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function canonicalDialogueMemoryKey(value: string): string {
  return resolveCanonicalMemoryKey(normalizeMemoryKey(value));
}

function mergeUserMemory(
  previous: DialogueState["userMemory"],
  ops: TurnEnvelope["memory_ops"],
  nowIso: string,
): DialogueState["userMemory"] {
  const next = userMemorySchema.parse(previous ?? {});
  let changed = false;

  for (const op of ops) {
    if (op.kind === "episode" || op.op === "contest") {
      continue;
    }

    const key = canonicalDialogueMemoryKey(op.key);
    const value = clip(op.value, 160);
    const nextValue = op.op === "forget" ? null : value || null;

    if (key === "name") {
      next.name = nextValue;
      changed = true;
    } else if (key === "preferred_name") {
      next.preferredName = nextValue;
      changed = true;
    } else if (key === "preferred_language") {
      next.preferredLanguage = nextValue;
      changed = true;
    } else if (key === "preferred_tone") {
      next.preferredTone = nextValue;
      changed = true;
    } else if (key === "response_style_preference") {
      next.responseStyle = nextValue;
      changed = true;
    } else if (key === "timezone") {
      next.timezone = nextValue;
      changed = true;
    }
  }

  if (changed) {
    next.updatedAt = nowIso;
  }

  return userMemorySchema.parse(next);
}

function digestAssistantBlocks(blocks: AssistantMessageBlock[]): string | null {
  const types = blocks
    .map((block) => block.type)
    .filter((type, index, values) => values.indexOf(type) === index)
    .slice(0, 8);
  return types.length ? `blocks:${types.join(",")}` : null;
}

function digestAssistantText(text: string, blocks: AssistantMessageBlock[] = []): string | null {
  const cleaned = scrubPrivateSnippet(text, 360);
  if (cleaned) {
    return cleaned;
  }
  return digestAssistantBlocks(blocks);
}

function buildTurnTrace(input: {
  userMessage: string;
  assistantText: string;
  workload?: string | null;
  nowIso: string;
}): z.output<typeof turnTraceSchema> | null {
  const user = scrubPrivateSnippet(input.userMessage, 280);
  if (!user) {
    return null;
  }
  const assistant = scrubPrivateSnippet(input.assistantText, 320);
  return turnTraceSchema.parse({
    at: input.nowIso,
    user,
    assistant: assistant || null,
    workload: input.workload ?? null,
  });
}

function phraseEdge(text: string, edge: "start" | "end"): string | null {
  const normalized = scrubPrivateSnippet(text, 2_000);
  if (!normalized) return null;
  const sentences = normalized.split(/(?<=[.!?])\s+/).filter(Boolean);
  const selected = edge === "start" ? sentences[0] : sentences.at(-1);
  return selected ? selected.split(/\s+/).slice(0, 8).join(" ").slice(0, 120) : null;
}

export function deriveConversationDynamics(
  previous: DialogueState["conversationDynamics"],
  assistantText: string,
): DialogueState["conversationDynamics"] {
  const chars = assistantText.replace(/\s+/g, " ").trim().length;
  if (chars === 0) return previous;
  const turnCount = previous.turnCount + 1;
  const averageReplyChars = Math.round(
    (previous.averageReplyChars * previous.turnCount + chars) / turnCount,
  );
  const opener = phraseEdge(assistantText, "start");
  const closer = phraseEdge(assistantText, "end");
  return conversationDynamicsSchema.parse({
    turnCount,
    averageReplyChars,
    recentOpeners: opener ? appendUnique(previous.recentOpeners, [opener], 6) : previous.recentOpeners,
    recentClosers: closer ? appendUnique(previous.recentClosers, [closer], 6) : previous.recentClosers,
  });
}

function extractSessionIdFromMetadata(metadata: unknown): string | null {
  const record = readRecord(metadata);
  const direct = readString(record?.sessionId);
  if (direct && uuidSchema.safeParse(direct).success) {
    return direct;
  }
  const chat = readRecord(record?.chat);
  const chatSessionId = readString(chat?.sessionId);
  return chatSessionId && uuidSchema.safeParse(chatSessionId).success ? chatSessionId : null;
}

export function resolveDialogueStateSessionId(metadata: unknown): string | null {
  return extractSessionIdFromMetadata(metadata);
}

export function applyCanonicalDialogueStateToMetadata(input: {
  metadata?: Record<string, unknown>;
  snapshot: DialogueStateSnapshot;
  userMessage?: string;
  /** Kullanıcı düzeyinde kalıcı etkileşim derinliği (oturumlar arası rapport). */
  userInteractionCount?: number;
}): Record<string, unknown> {
  const existing = input.metadata ?? {};
  const compactContext = readRecord(existing.compactContext) ?? {};
  const rollingSummary = readRecord(compactContext.rollingSummary) ?? {};
  const state = sanitizeDialogueStateSnapshot(input.snapshot.state);
  const referenceContext = input.userMessage
    ? deriveReferenceContext(state.salience, input.userMessage)
    : {
        referenceMode: state.salience.referenceMode,
        referentCandidates: state.salience.referentCandidates,
      };
  return {
    ...existing,
    dialogueStateRevision: input.snapshot.revision,
    dialogueStateSource: DIALOGUE_STATE_METADATA_SOURCE,
    dialogueStateUserId: input.snapshot.userId,
    dialogueStateSessionId: input.snapshot.sessionId,
    compactContext: {
      ...compactContext,
      source: DIALOGUE_STATE_METADATA_SOURCE,
      ownerUserId: input.snapshot.userId,
      ownerSessionId: input.snapshot.sessionId,
      rollingSummary: {
        ...rollingSummary,
        userGoal: state.goal,
        assistantState: state.stage,
        openLoops: state.openLoops,
      },
      turns: state.turns,
      salience: {
        ...state.salience,
        ...referenceContext,
      },
      lastAssistantBlocksDigest: state.lastAssistantDigest,
      conversationDynamics: state.conversationDynamics,
      // Biriken duygusal duruş: moodTrend/register/turnCount + kullanıcı-düzeyi
      // kalıcı etkileşim derinliğinden türetilir ve downstream (context-builder,
      // generation) yapısal olarak tüketir. Ayrı bir sistem değil, aynı state'in
      // davranışa dönmüş hâli.
      affectiveStance: deriveAffectiveStance(state, {
        userInteractionCount: input.userInteractionCount,
      }),
      userMemory: state.userMemory,
    },
  };
}

export function isTrustedDialogueStateMetadata(
  metadata: unknown,
  input: { userId: string; sessionId?: string | null },
): boolean {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const rootSource = readString(root?.dialogueStateSource);
  const compactSource = readString(compactContext?.source);
  const ownerUserId =
    readString(root?.dialogueStateUserId) ??
    readString(compactContext?.ownerUserId);
  const ownerSessionId =
    readString(root?.dialogueStateSessionId) ??
    readString(compactContext?.ownerSessionId);
  if (rootSource !== DIALOGUE_STATE_METADATA_SOURCE && compactSource !== DIALOGUE_STATE_METADATA_SOURCE) {
    return false;
  }
  if (ownerUserId !== input.userId) {
    return false;
  }
  if (input.sessionId && ownerSessionId && ownerSessionId !== input.sessionId) {
    return false;
  }
  return true;
}

export function buildDialogueStateFallbackFromMetadata(
  metadata: unknown,
  input?: { userId: string; sessionId?: string | null },
): DialogueState {
  if (input && !isTrustedDialogueStateMetadata(metadata, input)) {
    return dialogueStateSchema.parse({});
  }
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const chatContext = readRecord(root?.chatContext);
  const rollingSummary = readRecord(compactContext?.rollingSummary ?? chatContext?.rollingSummary);
  const openLoopsRaw = Array.isArray(rollingSummary?.openLoops)
    ? rollingSummary.openLoops
    : [];
  const parsed = dialogueStateSchema.parse({
    goal: scrubOptionalSnippet(rollingSummary?.userGoal, 500),
    stage: scrubOptionalSnippet(rollingSummary?.assistantState, 240),
    openLoops: openLoopsRaw.map(String).map((item) => scrubPrivateSnippet(item, 500)).filter(Boolean).slice(0, 12),
    lastAssistantDigest:
      scrubOptionalSnippet(compactContext?.lastAssistantBlocksDigest, 500) ??
      scrubOptionalSnippet(chatContext?.lastAssistantBlocksDigest, 500),
    turns: sanitizeTurnTraces(compactContext?.turns),
    salience: sanitizeSalience(compactContext?.salience),
    userMemory: readRecord(compactContext?.userMemory ?? chatContext?.userMemory) ?? {},
  });
  return sanitizeDialogueStateSnapshot(parsed);
}

export function mergeDialogueState(input: {
  previous?: unknown;
  fallback?: unknown;
  userMessage: string;
  assistantText: string;
  assistantBlocks?: AssistantMessageBlock[];
  envelope?: TurnEnvelope | null;
  toolResults?: AgentToolResult[];
  workload?: string | null;
  omitUserMemory?: boolean;
  memoryRefs?: DialogueStateTurnInput["memoryRefs"];
  now?: Date;
}): DialogueState {
  const nowIso = (input.now ?? new Date()).toISOString();
  const previous = dialogueStateSchema.parse(input.previous ?? input.fallback ?? {});
  const fallback = dialogueStateSchema.parse(input.fallback ?? {});
  const envelope = input.envelope;
  const goalOps = envelope?.goal_ops ?? [];
  const followUps = envelope?.follow_ups ?? [];
  const memoryOps = envelope?.memory_ops ?? [];
  const toolRequests = envelope?.tool_requests ?? [];
  const toolResults = input.toolResults ?? [];

  let goal = previous.goal ?? fallback.goal;
  let stage = previous.stage ?? fallback.stage;
  let retainedOpenLoops = previous.openLoops;
  const newLoops: string[] = [];

  for (const op of goalOps) {
    if (op.op === "open") {
      goal = op.step ?? op.next ?? goal ?? scrubPrivateSnippet(input.userMessage, 240);
      stage = "open";
    } else if (op.op === "advance") {
      stage = op.step ?? op.next ?? stage ?? "advance";
    } else if (op.op === "complete") {
      stage = "complete";
      retainedOpenLoops = [];
    } else if (op.op === "block") {
      stage = "blocked";
      if (op.next || op.step) {
        newLoops.push(op.next ?? op.step ?? "");
      }
    }
  }

  for (const followUp of followUps) {
    newLoops.push(scrubPrivateSnippet(`${followUp.due}: ${followUp.topic} — ${followUp.nudge}`, 500));
  }

  const factsTouched = appendUnique(
    previous.factsTouched,
    memoryOps.map((op) => op.key),
    80,
  );
  const requestedToolHistory = toolRequests.map((request) => ({
    tool: request.tool,
    at: nowIso,
    status: "requested" as const,
  }));
  const completedToolHistory = toolResults.map((result) => ({
    tool: result.tool,
    at: nowIso,
    status: result.ok ? "completed" as const : "failed" as const,
    durationMs: Math.max(0, Math.round(result.durationMs)),
    errorCode: result.error?.code ?? null,
  }));
  const toolHistory = [
    ...completedToolHistory,
    ...requestedToolHistory,
    ...previous.toolHistory,
  ].slice(0, 40);
  const moodTrend = envelope
    ? [
        {
          mood: envelope.affect.user_mood_guess,
          energy: envelope.affect.energy,
          at: nowIso,
        },
        ...previous.moodTrend,
      ].slice(0, 20)
    : previous.moodTrend;
  const conversationDynamics = deriveConversationDynamics(
    previous.conversationDynamics,
    input.assistantText,
  );
  const userMemory = input.omitUserMemory
    ? userMemorySchema.parse({})
    : mergeUserMemory(previous.userMemory ?? fallback.userMemory, memoryOps, nowIso);
  const turnTrace = buildTurnTrace({
    userMessage: input.userMessage,
    assistantText: input.assistantText,
    workload: input.workload,
    nowIso,
  });
  const salience = deriveTurnSalience({
    previous: previous.salience ?? fallback.salience,
    userMessage: input.userMessage,
    assistantText: input.assistantText,
    envelope,
    newLoops,
    toolResults,
    nowIso,
  });

  return sanitizeDialogueStateSnapshot(
    dialogueStateSchema.parse({
      ...previous,
      goal: goal ? scrubPrivateSnippet(goal, 500) : null,
      stage: stage ? scrubPrivateSnippet(stage, 240) : (input.workload ?? previous.stage),
      openLoops: appendUnique(retainedOpenLoops, newLoops, 12),
      lastAssistantDigest:
        digestAssistantText(input.assistantText, input.assistantBlocks ?? []) ??
        previous.lastAssistantDigest,
      styleSignature: {
        opener: conversationDynamics.recentOpeners[0] ?? previous.styleSignature.opener,
        closer: conversationDynamics.recentClosers[0] ?? previous.styleSignature.closer,
      },
      userRegister: envelope?.affect.register ?? previous.userRegister ?? fallback.userRegister,
      factsTouched,
      toolHistory,
      moodTrend,
      lastProactiveAt: previous.lastProactiveAt,
      conversationDynamics,
      turns: turnTrace ? [turnTrace, ...previous.turns].slice(0, 12) : previous.turns,
      salience,
      userMemory,
      memoryRefs: input.memoryRefs
        ? {
            revision: input.memoryRefs.revision,
            factIds: input.memoryRefs.factIds ?? [],
            episodeIds: input.memoryRefs.episodeIds ?? [],
          }
        : previous.memoryRefs,
    }),
  );
}

// ── Affective stance ─────────────────────────────────────────────────────────
// Elyan'ın "ruhu" ayrı bir sistem değil: zaten biriken dialogue-state alanlarını
// (moodTrend geçmişi, userRegister, turnCount) kalıcı bir duygusal duruşa
// indirger. Model her turda duyguyu sıfırdan tahmin edip unutmak yerine, oturum
// boyunca taşınan bir ruh haline ve BÜYÜYEN bir yakınlığa göre davranır. Bu saf
// türetme hem bağlam direktifini hem de generation sıcaklığını besler (yalnız
// prompt değil, davranışsal dial).

export type AffectiveMood =
  | "positive"
  | "frustrated"
  | "anxious"
  | "sad"
  | "tired"
  | "curious"
  | "neutral";

export type AffectiveStance = {
  mood: AffectiveMood;
  energy: "low" | "mid" | "high";
  register: string | null;
  /** 0..1, oturum sürdükçe doygunlaşarak büyüyen kurulmuş yakınlık. */
  rapport: number;
  /** 0..1, son turlardaki ruh hali oynaklığı (istikrar sinyali). */
  volatility: number;
  /** Modele giden tek, biriken-durumdan türetilmiş yapısal direktif. */
  directive: string;
};

const AFFECTIVE_MOOD_KEYWORDS: Array<[AffectiveMood, RegExp]> = [
  [
    "frustrated",
    /sinir|öfke|ofke|kızg|kizg|hayal\s*kır|hayal\s*kir|bık|bik|frustrat|angry|annoy|upset|irritat/i,
  ],
  [
    "anxious",
    /kayg|endişe|endise|stres|gergin|panik|anxious|worried|worry|stress|nervous|overwhelm/i,
  ],
  [
    "sad",
    /üzg|uzg|hüzün|huzun|mutsuz|kötü\s*his|kotu\s*his|sad|down|unhappy|depress|lonely|yalnız|yalniz/i,
  ],
  ["tired", /yorgun|bitkin|bitap|tükendi|tukendi|tired|exhaust|burn.?out|drained/i],
  [
    "positive",
    /mutlu|sevin|keyif|heyecan|memnun|harika|müthiş|muthis|happy|excited|glad|great|joy|positive|pleased/i,
  ],
  ["curious", /merak|ilgi|öğrenmek\s*ist|ogrenmek\s*ist|curious|interested|intrigued/i],
];

function classifyMood(raw: string): AffectiveMood {
  const value = raw.trim().toLowerCase();
  if (!value || value === "unknown" || value === "neutral") return "neutral";
  for (const [mood, pattern] of AFFECTIVE_MOOD_KEYWORDS) {
    if (pattern.test(value)) return mood;
  }
  return "neutral";
}

/**
 * Fold the persisted dialogue state into a stable affective stance. Pure over
 * existing fields — no new persistence. Returns null only when there is nothing
 * to say (fresh, moodless session), so callers keep their neutral default.
 */
export function deriveAffectiveStance(
  state: DialogueState,
  options: { userInteractionCount?: number } = {},
): AffectiveStance | null {
  const parsed = dialogueStateSchema.parse(state ?? {});
  const trend = parsed.moodTrend; // newest-first
  // Rapport, oturum içi turlarla kullanıcı düzeyinde KALICI etkileşim
  // derinliğini birleştirir: dönen bir kullanıcı, yeni oturuma sıfırdan değil,
  // önceki oturumlarda kurulmuş yakınlıkla başlar. userInteractionCount yoksa
  // (eski çağrı) yalnız oturum turları kullanılır — davranış değişmez.
  const persistentDepth = Math.max(0, Math.round(options.userInteractionCount ?? 0));
  const turnCount = parsed.conversationDynamics.turnCount + persistentDepth;
  const register = parsed.userRegister ? clip(parsed.userRegister, 60) : null;

  // Recency-weighted mood vote over the recent window (newest weighs most).
  const window = trend.slice(0, 6);
  const votes = new Map<AffectiveMood, number>();
  window.forEach((item, index) => {
    const mood = classifyMood(item.mood);
    if (mood === "neutral") return;
    votes.set(mood, (votes.get(mood) ?? 0) + 1 / (index + 1));
  });
  let mood: AffectiveMood = "neutral";
  let best = 0;
  for (const [candidate, score] of votes) {
    if (score > best) {
      best = score;
      mood = candidate;
    }
  }

  const energy =
    window.find((item) => classifyMood(item.mood) !== "neutral")?.energy ??
    window[0]?.energy ??
    "mid";

  // Volatility: fraction of adjacent mood changes across the recent window.
  let changes = 0;
  for (let i = 1; i < window.length; i += 1) {
    if (classifyMood(window[i].mood) !== classifyMood(window[i - 1].mood)) {
      changes += 1;
    }
  }
  const volatility = window.length > 1 ? changes / (window.length - 1) : 0;

  // Rapport grows with sustained interaction and saturates — the concrete
  // backing for "grows closer over time" instead of a hollow prompt claim.
  const rapport = turnCount > 0 ? turnCount / (turnCount + 8) : 0;

  if (mood === "neutral" && rapport < 0.2 && !register) {
    return null;
  }

  return {
    mood,
    energy,
    register,
    rapport,
    volatility,
    directive: buildStanceDirective({ mood, energy, rapport, volatility }),
  };
}

function buildStanceDirective(input: {
  mood: AffectiveMood;
  energy: AffectiveStance["energy"];
  rapport: number;
  volatility: number;
}): string {
  const parts: string[] = [];
  const close = input.rapport >= 0.55;
  const familiar = input.rapport >= 0.3;

  switch (input.mood) {
    case "frustrated":
      parts.push(
        "Kullanıcı son turlarda gergin/zorlanıyor: önce kısa ve insanca kabullen, savunmaya geçme ya da fazla özür dizme; sonra doğrudan çöz",
      );
      break;
    case "anxious":
      parts.push(
        "Kullanıcıda kaygı/stres sinyali var: sakinleştirici, net ve adımlı ol; belirsizliği azalt, yükünü hafiflet",
      );
      break;
    case "sad":
      parts.push(
        "Kullanıcı düşük/hüzünlü: önce içtenlikle yanında ol, aceleyle çözüme atlama; sıcak ve yumuşak bir tonla eşlik et",
      );
      break;
    case "tired":
      parts.push(
        "Kullanıcı yorgun: kısa tut, gereksiz detaydan kaçın, en pratik yolu ver",
      );
      break;
    case "positive":
      parts.push(
        "Hava olumlu: enerjisine eşlik et, rahat ve canlı ol, yeri gelirse hafif espriye açık",
      );
      break;
    case "curious":
      parts.push(
        "Kullanıcı meraklı: öğretici ol ama boğma; bir adım ötesini açacak küçük bir kanca bırak",
      );
      break;
    default:
      parts.push("Sıcak, doğal ve olgun bir arkadaş gibi konuş");
  }

  if (close) {
    parts.push(
      "kurulu yakınlık yüksek: samimi ve senli-benli ol, ismini doğal kullan, resmiyeti bırak",
    );
  } else if (familiar) {
    parts.push("tanışıklık oturmuş: içten ol ama abartma");
  }

  if (input.volatility >= 0.6) {
    parts.push("ruh hali dalgalı: dengeli ve istikrarlı dur, ani ton değişimi yapma");
  }

  parts.push("bu iç sinyali asla açıkça söyleme");
  return parts.join("; ") + ".";
}

// ── User-level persistent relationship depth ─────────────────────────────────
// Kümülatif etkileşim derinliği, mevcut brain_memory_facts tablosunda tek bir
// canonical satırda tutulur (yeni tablo yok). Oturumlar arası büyüyen yakınlığın
// kaynağı budur; rapport'a userInteractionCount olarak beslenir.
const RELATIONSHIP_DEPTH_KEY = "relationship_depth";

export async function readRelationshipDepthOnDb(
  db: DialogueDb,
  userId: string,
): Promise<number> {
  try {
    const rows = await db
      .select({ value: brainMemoryFacts.value })
      .from(brainMemoryFacts)
      .where(
        and(
          eq(brainMemoryFacts.userId, userId),
          eq(brainMemoryFacts.canonicalKey, RELATIONSHIP_DEPTH_KEY),
          eq(brainMemoryFacts.lifecycleStatus, "active"),
          eq(brainMemoryFacts.conflictStatus, "active"),
        ),
      )
      .orderBy(desc(brainMemoryFacts.updatedAt))
      .limit(1);
    const parsed = Number.parseInt(rows[0]?.value ?? "0", 10);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
  } catch {
    return 0;
  }
}

export async function readRelationshipDepth(
  app: FastifyInstance,
  userId: string,
): Promise<number> {
  const cache =
    relationshipDepthCache.get(app) ?? new Map<string, RelationshipDepthCacheEntry>();
  relationshipDepthCache.set(app, cache);
  const now = Date.now();
  const cached = cache.get(userId);
  if (cached && cached.expiresAt > now) {
    return cached.pending ?? cached.value;
  }

  const entry = cached ?? { value: 0, expiresAt: 0 };
  if (entry.pending) return entry.pending;

  const pending = readRelationshipDepthOnDb(app.db, userId).then((value) => {
    entry.value = value;
    entry.expiresAt = Date.now() + RELATIONSHIP_DEPTH_CACHE_TTL_MS;
    return value;
  }).catch(() => {
    entry.value = 0;
    entry.expiresAt = Date.now() + 1_000;
    return 0;
  }).finally(() => {
    entry.pending = undefined;
  });
  entry.pending = pending;
  boundedCacheInsert(
    cache,
    userId,
    entry,
    RELATIONSHIP_DEPTH_CACHE_MAX_ENTRIES,
  );
  return pending;
}

export function invalidateRelationshipDepthCache(
  app: FastifyInstance,
  userId: string,
): void {
  relationshipDepthCache.get(app)?.delete(userId);
}

/** Best-effort +1 to the user's lifetime interaction depth. Never throws. */
export async function bumpRelationshipDepthOnDb(
  db: DialogueDb,
  userId: string,
): Promise<void> {
  try {
    const rows = await db
      .select({ id: brainMemoryFacts.id, value: brainMemoryFacts.value })
      .from(brainMemoryFacts)
      .where(
        and(
          eq(brainMemoryFacts.userId, userId),
          eq(brainMemoryFacts.canonicalKey, RELATIONSHIP_DEPTH_KEY),
          eq(brainMemoryFacts.lifecycleStatus, "active"),
          eq(brainMemoryFacts.conflictStatus, "active"),
        ),
      )
      .orderBy(desc(brainMemoryFacts.updatedAt))
      .limit(1);
    const existing = rows[0];
    if (existing) {
      const current = Number.parseInt(existing.value ?? "0", 10);
      const next = Math.min((Number.isFinite(current) ? current : 0) + 1, 1_000_000);
      await db
        .update(brainMemoryFacts)
        .set({ value: String(next), updatedAt: new Date() })
        .where(eq(brainMemoryFacts.id, existing.id));
      return;
    }
    await db.insert(brainMemoryFacts).values({
      userId,
      scope: "user",
      factType: "semantic",
      canonicalKey: RELATIONSHIP_DEPTH_KEY,
      key: RELATIONSHIP_DEPTH_KEY,
      value: "1",
      sourceKind: "relationship_meter",
    });
  } catch {
    /* warmth counter is best-effort; never block a turn on it */
  }
}

export async function bumpRelationshipDepth(
  app: FastifyInstance,
  userId: string,
): Promise<void> {
  await bumpRelationshipDepthOnDb(app.db, userId);
  invalidateRelationshipDepthCache(app, userId);
}

export async function readDialogueState(
  app: FastifyInstance,
  input: { userId: string; sessionId: string },
): Promise<DialogueStateSnapshot | null> {
  const key = dialogueStateCacheKey(input.userId, input.sessionId);
  const cache =
    dialogueStateCache.get(app) ?? new Map<string, DialogueStateCacheEntry>();
  dialogueStateCache.set(app, cache);
  const now = Date.now();
  const cached = cache.get(key);
  if (cached && cached.expiresAt > now) {
    return cached.pending ?? cached.value;
  }

  const entry = cached ?? { value: null, expiresAt: 0 };
  if (entry.pending) return entry.pending;

  const pending = readDialogueStateOnDb(app.db, input).then((value) => {
    entry.value = value;
    entry.expiresAt = Date.now() + DIALOGUE_STATE_CACHE_TTL_MS;
    return value;
  }).catch(() => {
    entry.value = null;
    entry.expiresAt = Date.now() + 500;
    return null;
  }).finally(() => {
    entry.pending = undefined;
  });
  entry.pending = pending;
  boundedCacheInsert(cache, key, entry, DIALOGUE_STATE_CACHE_MAX_ENTRIES);
  return pending;
}

export function invalidateDialogueStateCache(
  app: FastifyInstance,
  input: { userId: string; sessionId: string },
): void {
  dialogueStateCache
    .get(app)
    ?.delete(dialogueStateCacheKey(input.userId, input.sessionId));
}

export async function readDialogueStateOnDb(
  db: DialogueDb,
  input: { userId: string; sessionId: string },
  options: { includeStale?: boolean } = {},
): Promise<DialogueStateSnapshot | null> {
  const rows = await db
    .select({
      sessionId: dialogueStates.sessionId,
      userId: dialogueStates.userId,
      revision: dialogueStates.revision,
      state: dialogueStates.state,
      updatedAt: dialogueStates.updatedAt,
    })
    .from(dialogueStates)
    .where(and(eq(dialogueStates.sessionId, input.sessionId), eq(dialogueStates.userId, input.userId)))
    .limit(1);
  const row = rows[0];
  if (!row) {
    return null;
  }
  if (!options.includeStale && !isDialogueStateFresh(row.updatedAt)) {
    return null;
  }
  return {
    sessionId: row.sessionId,
    userId: row.userId,
    revision: row.revision,
    state: sanitizeDialogueStateSnapshot(dialogueStateSchema.parse(row.state)),
    updatedAt: row.updatedAt,
  };
}

export async function recordDialogueStateTurn(
  app: FastifyInstance,
  input: DialogueStateTurnInput,
): Promise<DialogueStateSnapshot | null> {
  const snapshot = await recordDialogueStateTurnOnDb(app.db, input, {
    foundationEnabled: isCognitiveFoundationEnabled(app, input.userId),
  });
  if (input.sessionId) {
    const key = dialogueStateCacheKey(input.userId, input.sessionId);
    if (snapshot) {
      const cache =
        dialogueStateCache.get(app) ?? new Map<string, DialogueStateCacheEntry>();
      dialogueStateCache.set(app, cache);
      boundedCacheInsert(
        cache,
        key,
        {
          value: snapshot,
          expiresAt: Date.now() + DIALOGUE_STATE_CACHE_TTL_MS,
        },
        DIALOGUE_STATE_CACHE_MAX_ENTRIES,
      );
    } else {
      invalidateDialogueStateCache(app, {
        userId: input.userId,
        sessionId: input.sessionId,
      });
    }
  }
  return snapshot;
}

export async function recordDialogueStateTurnOnDb(
  db: DialogueDb,
  input: DialogueStateTurnInput,
  options: { foundationEnabled: boolean },
): Promise<DialogueStateSnapshot | null> {
  if (!input.sessionId) {
    return null;
  }

  const fallback = options.foundationEnabled
    ? dialogueStateSchema.parse({})
    : buildDialogueStateFallbackFromMetadata(input.requestMetadata, {
        userId: input.userId,
        sessionId: input.sessionId,
      });
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const current = await readDialogueStateOnDb(db, {
      userId: input.userId,
      sessionId: input.sessionId,
    }, { includeStale: true });
    const currentIsFresh = current ? isDialogueStateFresh(current.updatedAt) : false;
    const nextState = mergeDialogueState({
      previous: currentIsFresh ? current?.state : undefined,
      fallback,
      userMessage: input.userMessage,
      assistantText: input.assistantText,
      assistantBlocks: input.assistantBlocks,
      envelope: input.envelope,
      toolResults: input.toolResults,
      workload: input.workload,
      omitUserMemory: options.foundationEnabled,
      memoryRefs: input.memoryRefs,
    });
    const nextRevision = (current?.revision ?? 0) + 1;
    const now = new Date();

    if (!current) {
      try {
        await db.insert(dialogueStates).values({
          sessionId: input.sessionId,
          userId: input.userId,
          revision: nextRevision,
          state: nextState,
          updatedAt: now,
        });
        return {
          sessionId: input.sessionId,
          userId: input.userId,
          revision: nextRevision,
          state: nextState,
          updatedAt: now,
        };
      } catch {
        continue;
      }
    }

    // Reuse the existing row when only its working-memory window expired. This
    // resets turn-local context without racing a second INSERT against the
    // session primary key.
    const updated = await db
      .update(dialogueStates)
      .set({
        revision: nextRevision,
        state: nextState,
        updatedAt: now,
      })
      .where(
        and(
          eq(dialogueStates.sessionId, input.sessionId),
          eq(dialogueStates.userId, input.userId),
          eq(dialogueStates.revision, current.revision),
        ),
      )
      .returning({ revision: dialogueStates.revision });
    if (updated.length > 0) {
      return {
        sessionId: input.sessionId,
        userId: input.userId,
        revision: nextRevision,
        state: nextState,
        updatedAt: now,
      };
    }
  }

  return null;
}
