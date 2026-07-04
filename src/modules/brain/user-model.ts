import { z } from "zod";
import type {
  CanonicalUserModel,
  MemoryRecallPackage,
  RetrievedMemory,
  UserProfileSnapshot,
} from "../../core/understanding/types.js";
import { sanitizeInboundContextText } from "../../lib/context-text-sanitizer.js";

const nullableText = z.string().trim().min(1).max(2_000).nullable();

export const canonicalUserModelSchema = z.object({
  revision: z.literal(1),
  identity: z.object({ displayName: nullableText, preferredName: nullableText }),
  communication: z.object({
    preferredLanguage: nullableText,
    preferredTone: nullableText,
    responseStyle: nullableText,
  }),
  locale: z.object({ timezone: nullableText }),
  evidence: z.array(z.object({
    key: z.string().min(1).max(160),
    value: z.string().max(2_000),
    source: z.enum(["explicit_user", "verified_memory", "inferred"]),
    confidence: z.number().min(0).max(1),
    updatedAt: z.string(),
  })).max(32),
});

export const memoryRecallPackageSchema = z.object({
  facts: z.array(z.object({
    key: z.string(), value: z.string(), confidence: z.number(), ageDays: z.number(),
  })).max(16),
  episodes: z.array(z.object({
    topic: z.string(), when: z.string(), summary: z.string(),
  })).max(8),
  style: z.object({
    preferredName: nullableText,
    preferredLanguage: nullableText,
    preferredTone: nullableText,
    responseStyle: nullableText,
  }),
});

const USER_MODEL_KEYS = new Set([
  "name", "preferred_name", "preferred_language", "preferred_tone",
  "response_style_preference", "timezone",
]);

function evidenceSource(memory: RetrievedMemory): "explicit_user" | "verified_memory" | "inferred" {
  if (memory.metadata?.source === "turn_envelope" || memory.metadata?.op === "write" || memory.metadata?.op === "update") {
    return "explicit_user";
  }
  if (memory.lastVerifiedAt || memory.isPinned) return "verified_memory";
  return "inferred";
}

function sourceRank(memory: RetrievedMemory): number {
  const source = evidenceSource(memory);
  return source === "explicit_user" ? 3 : source === "verified_memory" ? 2 : 1;
}

function selectByKey(memory: RetrievedMemory[], key: string): RetrievedMemory | undefined {
  return memory
    .filter((item) => item.key === key && item.conflictStatus !== "contested" && item.conflictStatus !== "superseded")
    .sort((a, b) => sourceRank(b) - sourceRank(a) || b.confidence - a.confidence || b.createdAt.getTime() - a.createdAt.getTime())[0];
}

function safeContextValue(value: string, maxLength = 2_000): string {
  return sanitizeInboundContextText(value, maxLength).text;
}

export function buildCanonicalUserModel(input: {
  memory: RetrievedMemory[];
  profile?: Partial<UserProfileSnapshot> | null;
}): CanonicalUserModel {
  const selected = new Map<string, RetrievedMemory>();
  for (const key of USER_MODEL_KEYS) {
    const value = selectByKey(input.memory, key);
    if (value) selected.set(key, value);
  }
  const read = (key: string) => {
    const value = selected.get(key)?.value;
    return value ? safeContextValue(value) || null : null;
  };
  const evidence = [...selected.entries()].map(([key, item]) => ({
    key,
    value: safeContextValue(item.value),
    source: evidenceSource(item),
    confidence: Math.max(0, Math.min(1, item.confidence)),
    updatedAt: item.createdAt.toISOString(),
  }));
  return canonicalUserModelSchema.parse({
    revision: 1,
    identity: {
      displayName: read("name") ?? input.profile?.displayName ?? null,
      preferredName: read("preferred_name") ?? input.profile?.preferredName ?? null,
    },
    communication: {
      preferredLanguage: read("preferred_language") ?? input.profile?.preferredLanguage ?? null,
      preferredTone: read("preferred_tone"),
      responseStyle: read("response_style_preference"),
    },
    locale: { timezone: read("timezone") },
    evidence,
  });
}

function ageDays(date: Date, now: Date): number {
  return Number(Math.max(0, (now.getTime() - date.getTime()) / 86_400_000).toFixed(1));
}

export function buildMemoryRecallPackage(input: {
  memory: RetrievedMemory[];
  userModel: CanonicalUserModel;
  now?: Date;
}): MemoryRecallPackage {
  const now = input.now ?? new Date();
  const active = input.memory.filter((item) => item.conflictStatus !== "contested" && item.conflictStatus !== "superseded");
  return memoryRecallPackageSchema.parse({
    facts: active.filter((item) => item.type !== "episode" && !USER_MODEL_KEYS.has(item.key)).slice(0, 16).map((item) => ({
      key: item.key, value: safeContextValue(item.value), confidence: item.confidence, ageDays: ageDays(item.createdAt, now),
    })),
    episodes: active.filter((item) => item.type === "episode" || item.source === "episodic_memory").slice(0, 8).map((item) => ({
      topic: item.key, when: item.createdAt.toISOString(), summary: safeContextValue(item.value),
    })),
    style: {
      preferredName: input.userModel.identity.preferredName,
      preferredLanguage: input.userModel.communication.preferredLanguage,
      preferredTone: input.userModel.communication.preferredTone,
      responseStyle: input.userModel.communication.responseStyle,
    },
  });
}
