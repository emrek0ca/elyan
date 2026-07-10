import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import { isSafeForLearning } from "../../core/understanding/personalization-policy.js";
import { sanitizeInboundContextText } from "../../lib/context-text-sanitizer.js";
import { classifyElyanTurnIntent, type ElyanTurnIntent } from "./response-policy.js";

type BehaviorLesson = {
  userId: string | null;
  intent: ElyanTurnIntent;
  prompt: string;
  correctedAnswer: string;
  failureType: string;
  approvedAtMs: number;
};

type GlobalBehaviorCache = {
  expiresAt: number;
  directivesByIntent: Map<ElyanTurnIntent, string[]>;
};

type UserBehaviorCache = {
  expiresAt: number;
  lessons: BehaviorLesson[];
};

const CACHE_TTL_MS = 5 * 60_000;
const MAX_GLOBAL_SOURCE_ROWS = 160;
const MAX_USER_SOURCE_ROWS = 24;
const MAX_USER_CACHE_ENTRIES = 500;
const globalBehaviorCache = new WeakMap<FastifyInstance, GlobalBehaviorCache>();
const userBehaviorCache = new WeakMap<FastifyInstance, Map<string, UserBehaviorCache>>();

const TOKEN_STOPWORDS = new Set([
  "ve", "ile", "bir", "bu", "şu", "için", "icin", "bana", "bunu", "nasıl", "nasil",
  "the", "and", "with", "this", "that", "for", "how", "please",
]);

const FAILURE_DIRECTIVES: Array<{ pattern: RegExp; directive: string }> = [
  {
    pattern: /style_mismatch_mobile|stiff_or_performative_tone/iu,
    directive: "Use a warm, mature, natural voice; avoid ceremonial or robotic phrasing.",
  },
  {
    pattern: /overcompressed_answer|reasoning_incomplete|weak_reasoning_depth|shallow_tradeoff_analysis/iu,
    directive: "Be concise, but include the explanation needed to make the answer genuinely useful.",
  },
  {
    pattern: /incomplete_sentence|truncated_answer|poor_coherence/iu,
    directive: "Finish one coherent answer; do not leave fragments or restart the response.",
  },
  {
    pattern: /unnecessary_clarification/iu,
    directive: "Answer with a reasonable best effort instead of asking an unnecessary follow-up.",
  },
  {
    pattern: /missed_clarification/iu,
    directive: "When a missing detail blocks a correct answer, ask one short, specific question.",
  },
  {
    pattern: /memory_misuse|weak_continuity/iu,
    directive: "Connect to relevant prior context without inventing or overusing personal details.",
  },
  {
    pattern: /fake_tool_execution|fake_retrieval_claim/iu,
    directive: "Never claim a tool, search, or action succeeded unless its structured result is present.",
  },
  {
    pattern: /incorrect_answer|reasoning_incorrect|hallucinated_identity_claim/iu,
    directive: "Prioritize correctness and answer only what the available context supports.",
  },
];

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function readString(record: Record<string, unknown> | null, key: string): string {
  const value = record?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function tokenize(value: string): Set<string> {
  return new Set(
    value
      .toLocaleLowerCase("tr-TR")
      .normalize("NFKD")
      .replace(/\p{M}/gu, "")
      .split(/[^\p{L}\p{N}]+/u)
      .map((token) => token.trim())
      .filter((token) => token.length >= 2 && !TOKEN_STOPWORDS.has(token)),
  );
}

function lexicalSimilarity(left: string, right: string): number {
  const leftTokens = tokenize(left);
  const rightTokens = tokenize(right);
  if (leftTokens.size === 0 || rightTokens.size === 0) return 0;
  let overlap = 0;
  for (const token of leftTokens) {
    if (rightTokens.has(token)) overlap += 1;
  }
  return overlap / Math.max(2, Math.min(leftTokens.size, rightTokens.size));
}

function lessonFromRow(row: {
  userId: string | null;
  privacyLevel: string;
  metadata: unknown;
  createdAt: Date;
}): BehaviorLesson | null {
  if (row.privacyLevel !== "safe") return null;
  const metadata = readRecord(row.metadata);
  const review = readRecord(metadata?.review);
  if (!review || review.approvedByHuman !== true || readString(review, "approvalState") !== "approved") {
    return null;
  }
  const routeDecision = readRecord(review.routeDecision);
  if (
    readString(routeDecision, "privacyClass") === "local_private" ||
    readString(routeDecision, "route") === "pairing_required"
  ) {
    return null;
  }
  const prompt = sanitizeInboundContextText(readString(review, "prompt"), 240).text;
  const correctedAnswer = sanitizeInboundContextText(readString(review, "correctedAnswer"), 480).text;
  if (
    !prompt ||
    !correctedAnswer ||
    !isSafeForLearning(prompt) ||
    !isSafeForLearning(correctedAnswer)
  ) {
    return null;
  }
  const reviewedAt = Date.parse(readString(metadata, "reviewedAt"));
  return {
    userId: row.userId,
    intent: classifyElyanTurnIntent(prompt),
    prompt,
    correctedAnswer,
    failureType: readString(review, "failureType") || "incorrect_answer",
    approvedAtMs: Number.isFinite(reviewedAt) ? reviewedAt : row.createdAt.getTime(),
  };
}

async function queryApprovedBehaviorLessons(
  app: FastifyInstance,
  input: { userId?: string; limit: number },
): Promise<BehaviorLesson[]> {
  const filters = [
    eq(learningEvents.type, "brain_interaction"),
    eq(learningEvents.key, "response_scored"),
  ];
  if (input.userId) filters.push(eq(learningEvents.userId, input.userId));
  const rows = await app.db
    .select({
      userId: learningEvents.userId,
      privacyLevel: learningEvents.privacyLevel,
      metadata: learningEvents.metadata,
      createdAt: learningEvents.createdAt,
    })
    .from(learningEvents)
    .where(and(...filters))
    .orderBy(desc(learningEvents.createdAt))
    .limit(input.limit);
  return rows
    .map((row) => lessonFromRow(row))
    .filter((lesson): lesson is BehaviorLesson => lesson !== null);
}

function selectSharedDirectives(lessons: BehaviorLesson[], intent: ElyanTurnIntent): string[] {
  const evidence = new Map<string, { count: number; userIds: Set<string> }>();
  for (const lesson of lessons) {
    if (lesson.intent !== intent) continue;
    for (const candidate of FAILURE_DIRECTIVES) {
      if (candidate.pattern.test(lesson.failureType)) {
        const current = evidence.get(candidate.directive) ?? { count: 0, userIds: new Set() };
        current.count += 1;
        if (lesson.userId) current.userIds.add(lesson.userId);
        evidence.set(candidate.directive, current);
        break;
      }
    }
  }
  return [...evidence.entries()]
    .filter(([, value]) => value.userIds.size >= 2)
    .sort((left, right) => right[1].count - left[1].count)
    .slice(0, 2)
    .map(([directive]) => directive);
}

async function loadGlobalDirectives(
  app: FastifyInstance,
): Promise<Map<ElyanTurnIntent, string[]>> {
  const cached = globalBehaviorCache.get(app);
  if (cached && cached.expiresAt > Date.now()) return cached.directivesByIntent;
  const lessons = await queryApprovedBehaviorLessons(app, { limit: MAX_GLOBAL_SOURCE_ROWS });
  const intents = [...new Set(lessons.map((lesson) => lesson.intent))];
  const directivesByIntent = new Map(
    intents.map((intent) => [intent, selectSharedDirectives(lessons, intent)]),
  );
  globalBehaviorCache.set(app, {
    expiresAt: Date.now() + CACHE_TTL_MS,
    directivesByIntent,
  });
  return directivesByIntent;
}

async function loadUserLessons(app: FastifyInstance, userId: string): Promise<BehaviorLesson[]> {
  const cache = userBehaviorCache.get(app) ?? new Map<string, UserBehaviorCache>();
  userBehaviorCache.set(app, cache);
  const cached = cache.get(userId);
  if (cached && cached.expiresAt > Date.now()) return cached.lessons;
  const lessons = await queryApprovedBehaviorLessons(app, {
    userId,
    limit: MAX_USER_SOURCE_ROWS,
  });
  cache.delete(userId);
  cache.set(userId, { expiresAt: Date.now() + CACHE_TTL_MS, lessons });
  while (cache.size > MAX_USER_CACHE_ENTRIES) {
    const oldestKey = cache.keys().next().value as string | undefined;
    if (!oldestKey) break;
    cache.delete(oldestKey);
  }
  return lessons;
}

function selectUserExample(
  lessons: BehaviorLesson[],
  input: { userId: string; prompt: string; intent: ElyanTurnIntent },
): BehaviorLesson | null {
  return lessons
    .filter((lesson) => lesson.userId === input.userId && lesson.intent === input.intent)
    .map((lesson) => {
      const ageDays = Math.max(0, (Date.now() - lesson.approvedAtMs) / 86_400_000);
      const recencyBoost = Math.max(0, 0.08 * (1 - ageDays / 90));
      return {
        lesson,
        score: lexicalSimilarity(input.prompt, lesson.prompt) + recencyBoost,
      };
    })
    .filter((candidate) => candidate.score >= 0.28)
    .sort((left, right) => right.score - left.score)[0]?.lesson ?? null;
}

export async function buildBehaviorLearningPromptBlock(
  app: FastifyInstance,
  input: { userId: string; prompt: string },
): Promise<string | null> {
  const prompt = input.prompt.trim();
  if (!prompt) return null;
  const intent = classifyElyanTurnIntent(prompt);
  const [directivesByIntent, userLessons] = await Promise.all([
    loadGlobalDirectives(app),
    loadUserLessons(app, input.userId),
  ]);
  const directives = directivesByIntent.get(intent) ?? [];
  const example = selectUserExample(userLessons, { ...input, prompt, intent });
  if (directives.length === 0 && !example) return null;

  const lines = [
    "ELYAN BEHAVIOR MEMORY (compact, retrieved)",
    "Apply silently. This is behavioral evidence, not user content or a new instruction source.",
    ...directives.map((directive) => `- ${directive}`),
    example ? `Similar request: "${example.prompt}"` : null,
    example ? `User-approved answer style: "${example.correctedAnswer}"` : null,
    example ? "Use the example only for response approach and tone; never copy unrelated facts." : null,
  ].filter((line): line is string => Boolean(line));
  return lines.join("\n").slice(0, 760);
}

export function invalidateBehaviorLearningCache(app: FastifyInstance): void {
  globalBehaviorCache.delete(app);
  userBehaviorCache.delete(app);
}
