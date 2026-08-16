import { createHash } from "node:crypto";
import { z } from "zod";

export const CHAT_CONTEXT_SNAPSHOT_VERSION = "chat_context.v2" as const;
export const CHAT_CONTEXT_MAX_MESSAGES = 14;
export const CHAT_CONTEXT_MAX_TOKENS = 3_200;

export const chatTurnKindValues = [
  "new_request",
  "follow_up",
  "correction",
  "continuation",
] as const;

export type ChatTurnKind = (typeof chatTurnKindValues)[number];

export type ChatContextSnapshotTurn = {
  messageId: string;
  role: "user" | "assistant";
  content: string;
  status?: string;
  createdAt: string;
  blockDigest?: string | null;
  blockTypes?: string[];
};

export type ChatContextSnapshot = {
  version: typeof CHAT_CONTEXT_SNAPSHOT_VERSION;
  sessionId: string;
  userMessageId: string;
  assistantMessageId: string;
  turnKind: ChatTurnKind;
  promptDigest: string;
  historyDigest: string;
  historyRevision: {
    lastCompletedMessageId: string | null;
    lastCompletedAt: string | null;
  };
  priorTurns: ChatContextSnapshotTurn[];
  priorAssistant: {
    messageId: string;
    visibleSummary: string;
    blockDigest: string | null;
    blockTypes: string[];
  } | null;
  integrity: "verified" | "reconstructed" | "degraded";
};

const snapshotTurnSchema = z.object({
  messageId: z.string().min(1).max(160),
  role: z.enum(["user", "assistant"]),
  content: z.string().min(1).max(16_000),
  status: z.string().min(1).max(40).optional(),
  createdAt: z.string().min(1).max(80),
  blockDigest: z.string().min(1).max(128).nullable().optional(),
  blockTypes: z.array(z.string().min(1).max(80)).max(32).optional(),
});

export const chatContextSnapshotSchema = z.object({
  version: z.literal(CHAT_CONTEXT_SNAPSHOT_VERSION),
  sessionId: z.string().min(1).max(160),
  userMessageId: z.string().min(1).max(160),
  assistantMessageId: z.string().min(1).max(160),
  turnKind: z.enum(chatTurnKindValues),
  promptDigest: z.string().regex(/^[a-f0-9]{16,128}$/),
  historyDigest: z.string().regex(/^[a-f0-9]{16,128}$/),
  historyRevision: z.object({
    lastCompletedMessageId: z.string().min(1).max(160).nullable(),
    lastCompletedAt: z.string().min(1).max(80).nullable(),
  }),
  priorTurns: z.array(snapshotTurnSchema).max(CHAT_CONTEXT_MAX_MESSAGES),
  priorAssistant: z
    .object({
      messageId: z.string().min(1).max(160),
      visibleSummary: z.string().min(1).max(800),
      blockDigest: z.string().min(1).max(128).nullable(),
      blockTypes: z.array(z.string().min(1).max(80)).max(32),
    })
    .nullable(),
  integrity: z.enum(["verified", "reconstructed", "degraded"]),
});

type SnapshotInput = {
  sessionId: string;
  userMessageId: string;
  assistantMessageId: string;
  prompt: string;
  priorTurns: ChatContextSnapshotTurn[];
  turnKind?: ChatTurnKind;
  integrity?: ChatContextSnapshot["integrity"];
};

function normalizeText(value: unknown, max = 16_000): string {
  return typeof value === "string"
    ? value.replace(/\s+/g, " ").trim().slice(0, max)
    : "";
}

function estimateTokens(value: string): number {
  return Math.max(1, Math.ceil(value.length / 4));
}

function clipToTokens(value: string, tokenLimit: number): string {
  const maxChars = Math.max(4, Math.floor(tokenLimit * 4));
  if (value.length <= maxChars) return value;
  return `${value.slice(0, Math.max(1, maxChars - 1)).trimEnd()}…`;
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!value || typeof value !== "object") return value;
  return Object.keys(value as Record<string, unknown>)
    .sort()
    .reduce<Record<string, unknown>>((result, key) => {
      result[key] = stableValue((value as Record<string, unknown>)[key]);
      return result;
    }, {});
}

function digest(value: unknown): string {
  return createHash("sha256")
    .update(JSON.stringify(stableValue(value)))
    .digest("hex");
}

function normalizeCreatedAt(value: unknown): string {
  if (value instanceof Date) return value.toISOString();
  const candidate = typeof value === "string" ? value.trim() : "";
  if (!candidate) return new Date(0).toISOString();
  const timestamp = new Date(candidate).getTime();
  return Number.isFinite(timestamp)
    ? new Date(timestamp).toISOString()
    : new Date(0).toISOString();
}

function sortTurns(turns: ChatContextSnapshotTurn[]): ChatContextSnapshotTurn[] {
  return [...turns].sort((left, right) => {
    const timeOrder = left.createdAt.localeCompare(right.createdAt);
    return timeOrder !== 0
      ? timeOrder
      : left.messageId.localeCompare(right.messageId);
  });
}

function normalizeTurns(turns: ChatContextSnapshotTurn[]): ChatContextSnapshotTurn[] {
  return sortTurns(
    turns
      .filter(
        (turn) =>
          (turn.role === "user" || turn.role === "assistant") &&
          (turn.status == null || turn.status === "completed"),
      )
      .map((turn) => ({
        messageId: normalizeText(turn.messageId, 160),
        role: turn.role,
        content: normalizeText(turn.content),
        status: "completed",
        createdAt: normalizeCreatedAt(turn.createdAt),
        blockDigest:
          typeof turn.blockDigest === "string" && turn.blockDigest.trim()
            ? turn.blockDigest.trim().slice(0, 128)
            : null,
        blockTypes: Array.isArray(turn.blockTypes)
          ? Array.from(
              new Set(
                turn.blockTypes
                  .filter((type): type is string => typeof type === "string")
                  .map((type) => type.trim().toLowerCase())
                  .filter(Boolean),
              ),
            ).slice(0, 32)
          : [],
      }))
      .filter((turn) => turn.messageId && turn.content),
  );
}

function selectBoundedTurns(turns: ChatContextSnapshotTurn[]): ChatContextSnapshotTurn[] {
  const pairs: ChatContextSnapshotTurn[][] = [];
  let groupStart = 0;
  while (groupStart < turns.length) {
    const createdAt = turns[groupStart]?.createdAt;
    let groupEnd = groupStart + 1;
    while (groupEnd < turns.length && turns[groupEnd]?.createdAt === createdAt) {
      groupEnd += 1;
    }
    const group = turns.slice(groupStart, groupEnd);
    const users = group.filter((turn) => turn.role === "user");
    const assistants = group.filter((turn) => turn.role === "assistant");
    const pairCount = Math.min(users.length, assistants.length);
    for (let index = 0; index < pairCount; index += 1) {
      pairs.push([users[index], assistants[index]]);
    }
    groupStart = groupEnd;
  }

  const selectedPairs: ChatContextSnapshotTurn[][] = [];
  let usedTokens = 0;
  for (let index = pairs.length - 1; index >= 0; index -= 1) {
    const pair = pairs[index];
    const pairTokens = pair.reduce(
      (total, turn) => total + estimateTokens(turn.content),
      0,
    );
    if (selectedPairs.length >= CHAT_CONTEXT_MAX_MESSAGES / 2) break;
    if (selectedPairs.length > 0 && usedTokens + pairTokens > CHAT_CONTEXT_MAX_TOKENS) {
      continue;
    }
    if (selectedPairs.length === 0 && pairTokens > CHAT_CONTEXT_MAX_TOKENS) {
      const halfBudget = Math.max(1, Math.floor(CHAT_CONTEXT_MAX_TOKENS / 2));
      selectedPairs.push([
        { ...pair[0], content: clipToTokens(pair[0].content, halfBudget) },
        { ...pair[1], content: clipToTokens(pair[1].content, halfBudget) },
      ]);
      usedTokens = CHAT_CONTEXT_MAX_TOKENS;
      break;
    }
    selectedPairs.push(pair);
    usedTokens += pairTokens;
  }

  return selectedPairs.reverse().flat();
}

export function resolveChatTurnKind(input: {
  prompt: string;
  hasPriorAssistant?: boolean;
}): ChatTurnKind {
  const normalized = normalizeText(input.prompt, 800).toLocaleLowerCase("tr-TR");
  if (
    /(?<!\p{L})(hayır|hayir|yanlış|yanlis|öyle değil|oyle degil|düzelt|duzelt|revize|ilg(ili|isiz)|alakasız|alakasiz)(?!\p{L})/iu.test(
      normalized,
    )
  ) {
    return "correction";
  }
  if (/^\s*(devam|devam et|sürdür|surdur|aynen|tamam)\b/iu.test(normalized)) {
    return "continuation";
  }
  if (
    input.hasPriorAssistant &&
    /\b(az önce|az once|önceki|onceki|yukarıdaki|yukaridaki|bunu|şunu|sunu|takip)\b/iu.test(
      normalized,
    )
  ) {
    return "follow_up";
  }
  return "new_request";
}

export function buildChatContextSnapshot(
  input: SnapshotInput,
): ChatContextSnapshot {
  const normalizedTurns = normalizeTurns(input.priorTurns);
  const boundedTurns = selectBoundedTurns(normalizedTurns);
  const lastCompleted = normalizedTurns.at(-1) ?? null;
  const priorAssistantTurn = [...boundedTurns]
    .reverse()
    .find((turn) => turn.role === "assistant");
  const priorAssistant = priorAssistantTurn
    ? {
        messageId: priorAssistantTurn.messageId,
        visibleSummary: priorAssistantTurn.content.slice(0, 800),
        blockDigest: priorAssistantTurn.blockDigest ?? null,
        blockTypes: priorAssistantTurn.blockTypes ?? [],
      }
    : null;
  const historyRevision = {
    lastCompletedMessageId: lastCompleted?.messageId ?? null,
    lastCompletedAt: lastCompleted?.createdAt ?? null,
  };
  const historyDigest = digest({
    revision: historyRevision,
    turns: boundedTurns,
  });

  return {
    version: CHAT_CONTEXT_SNAPSHOT_VERSION,
    sessionId: normalizeText(input.sessionId, 160),
    userMessageId: normalizeText(input.userMessageId, 160),
    assistantMessageId: normalizeText(input.assistantMessageId, 160),
    turnKind:
      input.turnKind ??
      resolveChatTurnKind({
        prompt: input.prompt,
        hasPriorAssistant: priorAssistant != null,
      }),
    promptDigest: digest(normalizeText(input.prompt)),
    historyDigest,
    historyRevision,
    priorTurns: boundedTurns,
    priorAssistant,
    integrity: input.integrity ?? "verified",
  };
}

export function snapshotConversation(
  snapshot: ChatContextSnapshot,
): Array<{ role: "user" | "assistant"; content: string }> {
  return snapshot.priorTurns.map(({ role, content }) => ({ role, content }));
}

export function readChatContextSnapshot(value: unknown): ChatContextSnapshot | null {
  const parsed = chatContextSnapshotSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export function verifyChatContextSnapshot(input: {
  snapshot: ChatContextSnapshot;
  sessionId: string;
  userMessageId: string;
  assistantMessageId: string;
  prompt: string;
}): { ok: true } | { ok: false; reason: string } {
  if (
    input.snapshot.sessionId !== input.sessionId ||
    input.snapshot.userMessageId !== input.userMessageId ||
    input.snapshot.assistantMessageId !== input.assistantMessageId
  ) {
    return { ok: false, reason: "identity_mismatch" };
  }
  if (input.snapshot.promptDigest !== digest(normalizeText(input.prompt))) {
    return { ok: false, reason: "prompt_digest_mismatch" };
  }
  const expectedHistoryDigest = digest({
    revision: input.snapshot.historyRevision,
    turns: input.snapshot.priorTurns,
  });
  if (input.snapshot.historyDigest !== expectedHistoryDigest) {
    return { ok: false, reason: "history_digest_mismatch" };
  }
  return { ok: true };
}
