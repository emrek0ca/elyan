import { and, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { dialogueStates } from "../../db/schema.js";
import type { AssistantMessageBlock } from "../chat/message-blocks.js";
import type { AgentToolResult } from "./tool-registry.js";
import { resolveCanonicalMemoryKey } from "./memory-key-policy.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import { isCognitiveFoundationEnabled } from "./cognitive-foundation-policy.js";

const uuidSchema = z.string().uuid();

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
  const cleaned = clip(text, 360);
  if (cleaned) {
    return cleaned;
  }
  return digestAssistantBlocks(blocks);
}

function phraseEdge(text: string, edge: "start" | "end"): string | null {
  const normalized = clip(text, 2_000);
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
}): Record<string, unknown> {
  const existing = input.metadata ?? {};
  const compactContext = readRecord(existing.compactContext) ?? {};
  const rollingSummary = readRecord(compactContext.rollingSummary) ?? {};
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
        userGoal: input.snapshot.state.goal,
        assistantState: input.snapshot.state.stage,
        openLoops: input.snapshot.state.openLoops,
      },
      lastAssistantBlocksDigest: input.snapshot.state.lastAssistantDigest,
      conversationDynamics: input.snapshot.state.conversationDynamics,
      userMemory: input.snapshot.state.userMemory,
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
    goal: readString(rollingSummary?.userGoal),
    stage: readString(rollingSummary?.assistantState),
    openLoops: openLoopsRaw.map(String).filter(Boolean).slice(0, 12),
    lastAssistantDigest:
      readString(compactContext?.lastAssistantBlocksDigest) ??
      readString(chatContext?.lastAssistantBlocksDigest),
    userMemory: readRecord(compactContext?.userMemory ?? chatContext?.userMemory) ?? {},
  });
  return parsed;
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
  const newLoops: string[] = [];

  for (const op of goalOps) {
    if (op.op === "open") {
      goal = op.step ?? op.next ?? goal ?? clip(input.userMessage, 240);
      stage = "open";
    } else if (op.op === "advance") {
      stage = op.step ?? op.next ?? stage ?? "advance";
    } else if (op.op === "complete") {
      stage = "complete";
    } else if (op.op === "block") {
      stage = "blocked";
      if (op.next || op.step) {
        newLoops.push(op.next ?? op.step ?? "");
      }
    }
  }

  for (const followUp of followUps) {
    newLoops.push(`${followUp.due}: ${followUp.topic} — ${followUp.nudge}`);
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

  return dialogueStateSchema.parse({
    ...previous,
    goal,
    stage: stage ?? input.workload ?? previous.stage,
    openLoops: appendUnique(previous.openLoops, newLoops, 12),
    lastAssistantDigest: digestAssistantText(input.assistantText, input.assistantBlocks ?? []) ?? previous.lastAssistantDigest,
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
    userMemory,
    memoryRefs: input.memoryRefs
      ? {
          revision: input.memoryRefs.revision,
          factIds: input.memoryRefs.factIds ?? [],
          episodeIds: input.memoryRefs.episodeIds ?? [],
        }
      : previous.memoryRefs,
  });
}

export async function readDialogueState(
  app: FastifyInstance,
  input: { userId: string; sessionId: string },
): Promise<DialogueStateSnapshot | null> {
  return readDialogueStateOnDb(app.db, input);
}

export async function readDialogueStateOnDb(
  db: DialogueDb,
  input: { userId: string; sessionId: string },
): Promise<DialogueStateSnapshot | null> {
  const rows = await db
    .select({
      sessionId: dialogueStates.sessionId,
      userId: dialogueStates.userId,
      revision: dialogueStates.revision,
      state: dialogueStates.state,
    })
    .from(dialogueStates)
    .where(and(eq(dialogueStates.sessionId, input.sessionId), eq(dialogueStates.userId, input.userId)))
    .limit(1);
  const row = rows[0];
  if (!row) {
    return null;
  }
  return {
    sessionId: row.sessionId,
    userId: row.userId,
    revision: row.revision,
    state: dialogueStateSchema.parse(row.state),
  };
}

export async function recordDialogueStateTurn(
  app: FastifyInstance,
  input: DialogueStateTurnInput,
): Promise<DialogueStateSnapshot | null> {
  return recordDialogueStateTurnOnDb(app.db, input, {
    foundationEnabled: isCognitiveFoundationEnabled(app, input.userId),
  });
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
    });
    const nextState = mergeDialogueState({
      previous: current?.state,
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
        };
      } catch {
        continue;
      }
    }

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
      };
    }
  }

  return null;
}
