import { and, desc, eq, gt, isNull, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { authIdentities, learningEvents, subscriptions, users } from "../../db/schema.js";
import { searchBrainMemory } from "../../modules/brain/memory.js";
import { buildContextPacketsFromMetadata, summarizeContextFreshness } from "./context-packets.js";
import { buildMemoryProfileSnapshot } from "./memory-profile.js";
import { filterRetrievedMemory } from "./personalization-policy.js";
import { extractProjectHints } from "./project-context.js";
import { buildDerivedHintBuckets, deriveLearningSignalsFromWorldSignals, toDerivedSignalInput } from "./world-signal-derived.js";
import type {
  ContextPacket,
  IntentClassification,
  MemoryProfileSnapshot,
  RetrievedMemory,
  TaskUnderstandingInput,
  UserProfileSnapshot,
  UserUnderstandingContext,
} from "./types.js";
import { listFreshWorldSignals } from "../../modules/mobile/service.js";
import { nlpDaemon } from "../../lib/nlp-daemon.js";

const MAX_HINTS = 12;
const MAX_CHARS = 4000;

function compactText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readStringValue(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readBooleanValue(record: Record<string, unknown> | null, key: string): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function readPersonalizationPrompt(metadata: Record<string, unknown> | undefined): string | null {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const candidates = [
    readStringValue(root, "userPersonalizationPrompt"),
    readStringValue(compactContext, "userPersonalizationPrompt"),
  ];
  for (const candidate of candidates) {
    const compact = compactText(candidate ?? "");
    if (compact) {
      return compact.slice(0, 200);
    }
  }
  return null;
}

function tokenize(value: string): Set<string> {
  return new Set(
    value
      .toLowerCase()
      .replace(/[^a-z0-9çğıöşü_\s.-]/gi, " ")
      .split(/\s+/)
      .filter((token) => token.length >= 3)
      .slice(0, 80),
  );
}

function scoreMemory(item: RetrievedMemory, queryTokens: Set<string>, now = Date.now()): number {
  const text = `${item.type} ${item.key} ${item.value}`;
  const itemTokens = tokenize(text);
  let overlap = 0;

  for (const token of queryTokens) {
    if (itemTokens.has(token)) {
      overlap += 1;
    }
  }

  const referenceTime = item.lastVerifiedAt?.getTime() ?? item.createdAt.getTime();
  const ageDays = Math.max(0, (now - referenceTime) / 86_400_000);
  const recency = Math.max(0, 1 - ageDays / 120);
  const stalenessPenalty =
    item.staleness === "contested" ? -1 : item.staleness === "stale" ? -0.5 : 0.14;
  const conflictPenalty =
    item.conflictStatus === "contested" ? -0.72 : item.conflictStatus === "superseded" ? -1 : 0.08;
  const pinBoost = item.isPinned ? 0.44 : 0;
  const verifiedBoost = item.lastVerifiedAt ? Math.max(0.08, Math.min(0.28, 0.28 - ageDays / 360)) : 0;
  return overlap * 1.8 + item.confidence + recency + stalenessPenalty + conflictPenalty + pinBoost + verifiedBoost;
}

function pushBounded(target: string[], value: string, state: { chars: number }) {
  const compact = compactText(value);

  if (!compact || target.includes(compact) || target.length >= MAX_HINTS || state.chars + compact.length > MAX_CHARS) {
    return;
  }

  target.push(compact);
  state.chars += compact.length;
}

function readFactValue(
  snapshot: MemoryProfileSnapshot | undefined,
  keys: string[],
): string | null {
  const facts = [...(snapshot?.identityFacts ?? []), ...(snapshot?.preferenceFacts ?? [])];

  for (const key of keys) {
    const match = facts.find((item) => item.key === key && compactText(item.value));
    if (match) {
      return compactText(match.value);
    }
  }

  return null;
}

function buildUserProfileSnapshot(input: {
  profile?: Partial<UserProfileSnapshot> | null;
  memorySnapshot?: MemoryProfileSnapshot;
}): UserProfileSnapshot | undefined {
  const displayName = compactText(String(input.profile?.displayName ?? ""));
  const preferredName =
    readFactValue(input.memorySnapshot, ["preferred_name", "name"]) ??
    compactText(String(input.profile?.preferredName ?? ""));
  const preferredLanguage =
    readFactValue(input.memorySnapshot, ["preferred_language", "language"]) ??
    compactText(String(input.profile?.preferredLanguage ?? ""));
  const planCode = compactText(String(input.profile?.planCode ?? "")).toLowerCase();
  const subscriptionStatus = compactText(String(input.profile?.subscriptionStatus ?? "")).toLowerCase();

  const snapshot: UserProfileSnapshot = {
    displayName: displayName || null,
    preferredName: preferredName || null,
    planCode: planCode || null,
    subscriptionStatus: subscriptionStatus || null,
    preferredLanguage: preferredLanguage || null,
  };

  return Object.values(snapshot).some((value) => value != null) ? snapshot : undefined;
}

async function loadSafeUserProfile(
  app: FastifyInstance,
  userId: string,
): Promise<Partial<UserProfileSnapshot> | null> {
  try {
    const [userRows, identityRows] = await Promise.all([
      app.db
        .select({
          displayName: users.displayName,
          planCode: subscriptions.planCode,
          subscriptionStatus: subscriptions.status,
        })
        .from(users)
        .leftJoin(subscriptions, eq(subscriptions.userId, users.id))
        .where(eq(users.id, userId))
        .limit(1),
      app.db
        .select({ displayName: authIdentities.displayName })
        .from(authIdentities)
        .where(eq(authIdentities.userId, userId))
        .limit(1),
    ]);

    const row = userRows[0];
    if (!row) {
      return null;
    }

    const displayName =
      compactText(String(row.displayName ?? "")) ||
      compactText(String(identityRows[0]?.displayName ?? "")) ||
      null;

    return {
      displayName,
      planCode: compactText(String(row.planCode ?? "")).toLowerCase() || null,
      subscriptionStatus: compactText(String(row.subscriptionStatus ?? "")).toLowerCase() || null,
    };
  } catch {
    return null;
  }
}

function extractEcosystemHints(input: {
  title?: string;
  message?: string;
  metadata?: Record<string, unknown>;
}): string[] {
  const text = `${input.title ?? ""} ${input.message ?? ""}`.toLowerCase();
  const hints = new Set<string>();

  if (/\belyan\b/i.test(text)) {
    hints.add("elyan_ecosystem");
  }
  if (/\b(desktop|runtime|pairing|pair|local runtime|local_runtime)\b/i.test(text)) {
    hints.add("desktop_runtime");
  }
  if (/\b(mobile|flutter|ios|android)\b/i.test(text)) {
    hints.add("mobile_surface");
  }
  if (/\b(backend|server|api|control plane|control-plane|control_plane)\b/i.test(text)) {
    hints.add("backend_control_plane");
  }
  if (/\b(fastify|drizzle|postgres|sql|api|backend|server)\b/i.test(text)) {
    hints.add("backend_control_plane");
  }
  if (/\b(brain|memory|retrieval|rag|learning|understanding)\b/i.test(text)) {
    hints.add("brain_understanding");
  }
  if (/\b(quota|billing|auth|subscription|credit|usage)\b/i.test(text)) {
    hints.add("policy_and_quota");
  }
  if (typeof input.metadata?.projectName === "string" && input.metadata.projectName.trim()) {
    hints.add(`project:${input.metadata.projectName.trim()}`);
    if (input.metadata.projectName.trim().toLowerCase() === "elyan") {
      hints.add("elyan_ecosystem");
    }
  }

  return [...hints].slice(0, 6);
}

function deriveTaskFrame(input: {
  intent: IntentClassification;
  message: string;
}): UserUnderstandingContext["taskFrame"] {
  return {
    goal: input.intent.taskFrame.goal,
    likelyAnswerShape: input.intent.taskFrame.likelyAnswerShape,
    reasoningMode: input.intent.taskFrame.reasoningMode,
    shouldClarify:
      input.intent.taskFrame.shouldClarify ||
      /^(bunu|şunu|sunu|this|that|it)\b/i.test(input.message.trim()) ||
      /^(düzelt|duzelt|fix it|improve this|optimize this)\b/i.test(input.message.trim()),
  };
}

function resolveMemoryEnabled(metadata: Record<string, unknown> | undefined): boolean {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const direct = readBooleanValue(root, "memoryEnabled");
  const nested = readBooleanValue(compactContext, "memoryEnabled");
  return nested ?? direct ?? true;
}

function deriveContinuitySummary(metadata: Record<string, unknown> | undefined) {
  const root = readRecord(metadata);
  const compactContext = readRecord(root?.compactContext);
  const chatContext = readRecord(root?.chatContext);
  const rollingSummary = readRecord(compactContext?.rollingSummary ?? chatContext?.rollingSummary);
  const openLoopsRaw = Array.isArray(rollingSummary?.openLoops) ? rollingSummary?.openLoops : [];
  return {
    userGoal: readStringValue(rollingSummary, "userGoal"),
    assistantState: readStringValue(rollingSummary, "assistantState"),
    openLoops: openLoopsRaw
      .map((item) => String(item ?? "").trim())
      .filter(Boolean)
      .slice(0, 4),
  };
}

function deriveClarificationDiagnostics(input: {
  intent: IntentClassification;
  message: string;
  continuity: { userGoal: string | null; assistantState: string | null; openLoops: string[] };
}): UserUnderstandingContext["clarificationDiagnostics"] {
  const text = compactText(input.message).toLowerCase();
  if (!input.intent.taskFrame.shouldClarify) {
    return {
      shouldClarify: false,
      ambiguityKind: "none",
      reason: "intent_confident_enough",
    };
  }
  if (/^(bunu|şunu|sunu|this|that|it|buradaki|bundaki)\b/.test(text)) {
    return {
      shouldClarify: true,
      ambiguityKind: "ambiguous_followup",
      reason: "referential_followup_without_clear_target",
    };
  }
  if (/^(düzelt|duzelt|fix|optimize|improve|rewrite|yenile)\b/.test(text)) {
    return {
      shouldClarify: true,
      ambiguityKind: "missing_target",
      reason: "action_requested_without_explicit_target",
    };
  }
  if (input.continuity.openLoops.length > 0 && /(ama|however|instead|yalnız|yalniz|fakat)/.test(text)) {
    return {
      shouldClarify: true,
      ambiguityKind: "conflicting_constraints",
      reason: "followup_may_change_prior_constraint_or_goal",
    };
  }
  return {
    shouldClarify: true,
    ambiguityKind: "insufficient_evidence",
    reason: "low_confidence_or_short_prompt",
  };
}

export function buildUserContextFromMemory(input: {
  userId: string;
  accountId: string;
  intent: IntentClassification;
  task: TaskUnderstandingInput;
  memory: RetrievedMemory[];
  profile?: Partial<UserProfileSnapshot> | null;
  contextPackets?: ContextPacket[];
}): UserUnderstandingContext {
  const filteredMemory = filterRetrievedMemory(input.memory).slice(0, MAX_HINTS);
  const memorySnapshot = buildMemoryProfileSnapshot(filteredMemory);
  const userProfile = buildUserProfileSnapshot({
    profile: input.profile,
    memorySnapshot,
  });
  const state = { chars: 0 };
  const ecosystemHints = extractEcosystemHints(input.task);
  const personalizationHints: string[] = [];
  const projectHints: string[] = [];
  const styleHints: string[] = [];
  const technicalHints: string[] = [];
  const safetyHints: string[] = [];
  const situationalHints: string[] = [];
  const behavioralHints: string[] = [];
  const environmentHints: string[] = [];
  const continuitySummary = deriveContinuitySummary(input.task.metadata);
  const clarificationDiagnostics = deriveClarificationDiagnostics({
    intent: input.intent,
    message: input.task.message,
    continuity: continuitySummary,
  });
  const memoryEnabled = resolveMemoryEnabled(input.task.metadata);
  const personalizationPrompt = readPersonalizationPrompt(input.task.metadata);
  const contextPackets = (input.contextPackets ?? []).slice(0, 8);
  const packetKinds = Array.from(new Set(contextPackets.map((packet) => packet.kind)));
  const healthContextUsed = packetKinds.includes("health_context");

  for (const hint of extractProjectHints(input.task)) {
    pushBounded(projectHints, hint, state);
  }

  for (const item of filteredMemory) {
    const hint = `${item.key}: ${item.value}`;

    if (item.type === "style") {
      pushBounded(styleHints, hint, state);
    } else if (item.type === "technical_stack") {
      pushBounded(technicalHints, hint, state);
    } else if (item.type === "project_context") {
      pushBounded(projectHints, hint, state);
    } else if (item.type === "correction") {
      pushBounded(safetyHints, hint, state);
    } else {
      pushBounded(personalizationHints, hint, state);
    }
  }

  const derivedHints = buildDerivedHintBuckets({
    memory: filteredMemory.map((item) => ({
      key: item.key,
      value: item.value,
      metadata:
        typeof item === "object" && item != null && "metadata" in item
          ? ((item as RetrievedMemory & { metadata?: Record<string, unknown> }).metadata ?? {})
          : {},
      staleness: item.staleness,
    })),
    requestText: input.task.message,
  });

  for (const hint of derivedHints.situationalHints) {
    pushBounded(situationalHints, hint, state);
  }
  for (const hint of derivedHints.behavioralHints) {
    pushBounded(behavioralHints, hint, state);
  }
  for (const hint of derivedHints.environmentHints) {
    pushBounded(environmentHints, hint, state);
  }

  if (input.intent.privacyRisk === "high" || input.intent.requiresLocalRuntime) {
    pushBounded(safetyHints, "Keep private local runtime data local unless the user explicitly allows sharing.", state);
  }

  if (input.intent.requiresCitation) {
    pushBounded(personalizationHints, "Prefer cited, source-grounded answers for this request.", state);
  }

  if (personalizationPrompt) {
    pushBounded(
      personalizationHints,
      `Explicit user personalization from settings: ${personalizationPrompt}`,
      state,
    );
  }

  if (healthContextUsed) {
    pushBounded(
      safetyHints,
      "Use health context only as short-lived wellbeing/readiness context; never diagnose, prescribe, or persist it as a permanent profile fact.",
      state,
    );
  }

  if (packetKinds.includes("calendar_context")) {
    pushBounded(
      safetyHints,
      "Use calendar context only as a derived schedule/load signal; never quote event titles, attendees, notes, or private calendar bodies.",
      state,
    );
  }

  if (packetKinds.includes("notification_context")) {
    pushBounded(
      safetyHints,
      "Use notification context only as attention/urgency context; never quote notification content or infer private relationships from it.",
      state,
    );
  }

  if (packetKinds.includes("device_context")) {
    pushBounded(
      safetyHints,
      "Use device context to adapt pacing and reliability expectations; never expose device identifiers, local paths, or private diagnostics.",
      state,
    );
  }

  return {
    userId: input.userId,
    accountId: input.accountId,
    intent: input.intent.primaryIntent,
    taskFrame: deriveTaskFrame({
      intent: input.intent,
      message: input.task.message,
    }),
    ecosystemHints,
    personalizationHints,
    projectHints,
    styleHints,
    technicalHints,
    safetyHints,
    situationalHints,
    behavioralHints,
    environmentHints,
    continuitySummary,
    clarificationDiagnostics,
    memoryEnabled,
    personalizationPrompt,
    memoryRelevanceSummary: filteredMemory.slice(0, 4).map((item) => `${item.key}: ${item.value}`),
    contextPackets,
    healthContextUsed,
    packetKinds,
    freshness: summarizeContextFreshness(contextPackets),
    retrievedMemory: filteredMemory,
    memorySnapshot,
    userProfile,
    tokenBudget: {
      maxHints: MAX_HINTS,
      maxChars: MAX_CHARS,
    },
  };
}

/* ── Extract quick user facts from the current message via C daemon ───── */
async function extractQuickFacts(message: string): Promise<{ name?: string; city?: string }> {
  const facts = await nlpDaemon.extractFacts(message).catch(() => []);
  const result: { name?: string; city?: string } = {};
  for (const f of facts) {
    if (f.k === "name" && f.v) result.name = f.v;
    if (f.k === "city" && f.v) result.city = f.v;
  }
  return result;
}

/* ── Derive C-level behavioral hints from world signals ───────────────── */
async function deriveCHintsFromWorldSignals(
  signals: Awaited<ReturnType<typeof listFreshWorldSignals>>,
): Promise<{ situational: string[]; behavioral: string[]; environmental: string[] }> {
  if (!nlpDaemon.isAvailable() || signals.length === 0) {
    return { situational: [], behavioral: [], environmental: [] };
  }

  const allHints = (
    await Promise.all(
      signals.slice(0, 6).map((signal) => {
        const facts = signal.facts as Record<string, unknown> | null;
        const readRecord = (v: unknown) =>
          v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
        const rf = readRecord(facts);
        const readNum = (k: string) => {
          const v = rf?.[k];
          return typeof v === "number" && Number.isFinite(v) ? v : null;
        };
        const readStr = (k: string) => {
          const v = rf?.[k];
          return typeof v === "string" && v.trim() ? v.trim() : null;
        };

        return nlpDaemon.deriveHints({
          kind:        signal.kind,
          summary:     signal.summary,
          energy:      readStr("energyLevel") ?? readStr("energy"),
          readiness:   readNum("readiness"),
          mobility:    readStr("mobility"),
          busyness:    readStr("busyness") ?? readStr("busyLevel"),
          attention:   readStr("attentionLoad") ?? readStr("notificationLoad"),
          city:        readStr("city"),
          freeMinutes: readNum("freeMinutesToday"),
        }).catch(() => []);
      }),
    )
  ).flat();

  const situational:   string[] = [];
  const behavioral:    string[] = [];
  const environmental: string[] = [];

  for (const h of allHints) {
    if (h.bucket === "situational"   && !situational.includes(h.hint))   situational.push(h.hint);
    if (h.bucket === "behavioral"    && !behavioral.includes(h.hint))    behavioral.push(h.hint);
    if (h.bucket === "environmental" && !environmental.includes(h.hint)) environmental.push(h.hint);
  }

  return {
    situational:   situational.slice(0, 4),
    behavioral:    behavioral.slice(0, 4),
    environmental: environmental.slice(0, 4),
  };
}

export async function buildUserContext(
  app: FastifyInstance,
  input: TaskUnderstandingInput & { intent: IntentClassification },
): Promise<UserUnderstandingContext> {
  const accountId    = input.accountId ?? input.userId;
  const memoryEnabled = resolveMemoryEnabled(input.metadata);
  const query        = `${input.title ?? ""} ${input.message ?? ""} ${input.intent.primaryIntent}`;
  const queryTokens  = tokenize(query);
  const now          = new Date();

  const contextPackets = app.config.ELYAN_WORLD_CONTEXT_PACKETS_ENABLED
    ? buildContextPacketsFromMetadata(input.metadata, {
        now,
        requestText: input.message,
        intent: input.intent.primaryIntent,
      })
    : [];

  /* Run all async ops in parallel for minimum latency */
  const [memorySearch, userProfile, quickFacts, freshWorldSignals] = await Promise.all([
    memoryEnabled
      ? searchBrainMemory(app, { userId: input.userId, query, limit: MAX_HINTS }).catch(() => ({ results: [] }))
      : Promise.resolve({ results: [] }),
    loadSafeUserProfile(app, input.userId),
    /* Quick C-based fact extraction from the current message */
    nlpDaemon.isAvailable() ? extractQuickFacts(input.message).catch(() => ({ name: undefined, city: undefined })) : Promise.resolve({ name: undefined, city: undefined }),
    listFreshWorldSignals(app, { userId: input.userId, limit: 12, maxAgeHours: 72 }).catch(() => []),
  ]);

  /* Enrich profile: if user name is unknown, try name extracted from this message */
  let enrichedProfile = userProfile;
  if (!userProfile?.displayName && quickFacts.name) {
    enrichedProfile = { ...userProfile, displayName: quickFacts.name };
  }

  const stableMemory = memorySearch.results.map((result) => ({
    id:             result.id,
    type:           result.memoryType,
    key:            result.title,
    value:          result.content,
    confidence:     result.confidence / 100,
    scope:          result.scope,
    source:         result.memorySource,
    createdAt:      new Date(result.updatedAt),
    staleness:      result.staleness,
    conflictStatus: result.conflictStatus,
    lastVerifiedAt: result.lastVerifiedAt ? new Date(result.lastVerifiedAt) : null,
    importanceScore: result.importanceScore,
    isPinned:       result.isPinned,
  }));

  const fallbackRows =
    !memoryEnabled || stableMemory.length >= Math.min(4, MAX_HINTS)
      ? []
      : await app.db
          .select({
            id:         learningEvents.id,
            type:       learningEvents.type,
            key:        learningEvents.key,
            value:      learningEvents.value,
            confidence: learningEvents.confidence,
            scope:      learningEvents.scope,
            source:     learningEvents.source,
            createdAt:  learningEvents.createdAt,
          })
          .from(learningEvents)
          .where(
            and(
              eq(learningEvents.userId, input.userId),
              or(isNull(learningEvents.expiresAt), gt(learningEvents.expiresAt, now)),
            ),
          )
          .orderBy(desc(learningEvents.createdAt))
          .limit(40);

  const worldDerivedMemory = !memoryEnabled
    ? []
    : deriveLearningSignalsFromWorldSignals(
        freshWorldSignals.map((signal) =>
          toDerivedSignalInput({
            signalId:   signal.signalId,
            kind:       signal.kind,
            summary:    signal.summary,
            confidence: signal.confidence,
            facts:      signal.facts,
            privacy:    signal.privacy,
            createdAt:  signal.createdAt,
          }),
        ),
      ).map((signal, index) => ({
        id:             `world-derived-${index}-${signal.key}`,
        type:           signal.type,
        key:            signal.key,
        value:          signal.value,
        confidence:     signal.confidence,
        scope:          signal.scope,
        source:         signal.source,
        createdAt:      new Date(),
        staleness:      "fresh" as const,
        conflictStatus: "active" as const,
        lastVerifiedAt: new Date(),
        importanceScore: 72,
        isPinned:       false,
        metadata:       signal.metadata,
      }));

  const allMemory = [
    ...stableMemory,
    ...worldDerivedMemory,
    ...fallbackRows.map((row) => ({ ...row, confidence: row.confidence / 100 })),
  ];

  /* Average document length for BM25 normalization */
  const avgDocLen = allMemory.length > 0
    ? allMemory.reduce((sum, m) => sum + tokenize(`${m.key} ${m.value}`).size, 0) / allMemory.length
    : 20;

  /* Score with BM25 (C daemon) when available; fall back to JS overlap scorer */
  let memory: typeof allMemory;
  if (nlpDaemon.isAvailable() && allMemory.length > 0) {
    /* Single IPC round-trip for all documents via bm25_batch */
    const docs = allMemory.map((item) => `${(item as { type?: string }).type ?? ""} ${item.key} ${item.value}`);
    const bm25Scores = await nlpDaemon.bm25Batch(query, docs, avgDocLen).catch(() => null);

    const scoringNow = Date.now();
    const scores = allMemory.map((item, i) => {
      const mem = item as RetrievedMemory;
      const bm25 = bm25Scores?.[i] ?? null;
      const referenceTime = mem.lastVerifiedAt?.getTime() ?? mem.createdAt.getTime();
      const ageDays       = Math.max(0, (scoringNow - referenceTime) / 86_400_000);
      const recency       = Math.max(0, 1 - ageDays / 120);
      const stalenessPenalty  = mem.staleness === "contested" ? -1 : mem.staleness === "stale" ? -0.5 : 0.14;
      const conflictPenalty   = mem.conflictStatus === "contested" ? -0.72 : mem.conflictStatus === "superseded" ? -1 : 0.08;
      const pinBoost      = mem.isPinned ? 0.44 : 0;
      const verifiedBoost = mem.lastVerifiedAt ? Math.max(0.08, Math.min(0.28, 0.28 - ageDays / 360)) : 0;
      const relevance     = bm25 != null ? bm25 * 2.2 : scoreMemory(mem, queryTokens, scoringNow);
      return relevance + mem.confidence + recency + stalenessPenalty + conflictPenalty + pinBoost + verifiedBoost;
    });

    memory = allMemory
      .map((item, i) => ({ item, score: scores[i] ?? 0 }))
      .sort((a, b) => b.score - a.score)
      .map(({ item }) => item)
      .slice(0, MAX_HINTS);
  } else {
    memory = allMemory
      .sort((left, right) => scoreMemory(right as RetrievedMemory, queryTokens) - scoreMemory(left as RetrievedMemory, queryTokens))
      .slice(0, MAX_HINTS);
  }

  /* Derive rich behavioral hints from world signals via C daemon */
  const cHints = await deriveCHintsFromWorldSignals(freshWorldSignals).catch(() => ({
    situational: [], behavioral: [], environmental: [],
  }));

  const ctx = buildUserContextFromMemory({
    userId:      input.userId,
    accountId,
    intent:      input.intent,
    task:        input,
    memory:      memory as RetrievedMemory[],
    profile:     enrichedProfile,
    contextPackets,
  });

  /* Merge C-derived hints into the context (deduplicated, bounded) */
  const mergeHints = (target: string[], incoming: string[]) => {
    const state = { chars: target.reduce((s, h) => s + h.length, 0) };
    for (const h of incoming) pushBounded(target, h, state);
  };
  mergeHints(ctx.situationalHints,   cHints.situational);
  mergeHints(ctx.behavioralHints,    cHints.behavioral);
  mergeHints(ctx.environmentHints,   cHints.environmental);

  return ctx;
}
