import { createHash } from "node:crypto";
import { and, asc, count, desc, eq, gte, inArray, lt, lte } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  chatSessions,
  proactiveTriggers,
  sessionGoals,
  worldSignals,
} from "../../db/schema.js";
import { readProactivePolicy } from "./proactive-engine.js";
import { recordProactiveEvent } from "./proactive-metrics.js";

/**
 * Autonomous suggestion generation.
 *
 * Until now a proactive trigger could only be born inside a chat turn, from
 * the model's own `follow_ups`. That means Elyan is only ever proactive about
 * conversations the user already started — it never notices anything on its
 * own.
 *
 * This observer closes that gap, under one non-negotiable rule:
 *
 * > **No suggestion without evidence.**
 *
 * Every candidate must name the row it came from, and that row must still
 * exist and still be in the state that made it interesting. A suggestion that
 * cannot be traced back is indistinguishable from an invention, and an
 * invented nudge is worse than silence — it teaches the user not to trust the
 * ones that are real.
 *
 * The second rule is quieter but just as important: **relevance beats
 * volume**. Open suggestions are capped per user, deduplicated by subject, and
 * expire. Elyan is allowed to be wrong occasionally; it is not allowed to be
 * noisy.
 */

export const OBSERVER_TRIGGER_KIND = "suggestion";

/** Hard ceiling on unresolved observer suggestions per user at any moment. */
const MAX_OPEN_SUGGESTIONS = 3;
/** A goal untouched this long is worth one "are we still doing this?". */
const STALLED_GOAL_DAYS = 10;
/** A due date further out than this is not yet actionable. */
const DUE_SOON_HOURS = 36;
/** World signals older than this are no longer "now". */
const SIGNAL_FRESH_HOURS = 12;
const MIN_SIGNAL_CONFIDENCE_BPS = 7_000;

export type ObservationSource =
  | "goal_due_soon"
  | "goal_stalled"
  | "world_signal";

export type ProactiveObservation = {
  source: ObservationSource;
  /** Primary key of the observed row. Verified to exist before firing. */
  ref: string;
  sessionId: string | null;
  topic: string;
  nudge: string;
  dueAt: Date;
  /**
   * True when the observation was derived from data the user has not marked
   * shareable. Such suggestions still fire in-app, but their push body stays
   * generic — a lock screen is not a private surface.
   */
  sensitive: boolean;
};

export type ObserverSweepResult = {
  usersConsidered: number;
  observed: number;
  created: number;
  skipped: number;
};

export function emptyObserverSweep(): ObserverSweepResult {
  return { usersConsidered: 0, observed: 0, created: 0, skipped: 0 };
}

function compact(value: string, max: number): string {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1)}…`;
}

/**
 * Subject identity, not content identity: re-wording the same nudge must not
 * produce a second trigger.
 */
export function observationDedupeKey(observation: {
  source: ObservationSource;
  ref: string;
}): string {
  return createHash("sha256")
    .update(`${observation.source}|${observation.ref}`)
    .digest("hex")
    .slice(0, 60);
}

/**
 * The evidence gate.
 *
 * A candidate is only allowed through if it names a source we know, a ref that
 * looks like a real row id, and carries text the user can recognise. Anything
 * else is dropped — never repaired, never guessed.
 */
export function hasGroundedEvidence(
  observation: Partial<ProactiveObservation> | null | undefined,
): observation is ProactiveObservation {
  if (!observation) return false;
  const knownSource =
    observation.source === "goal_due_soon" ||
    observation.source === "goal_stalled" ||
    observation.source === "world_signal";
  if (!knownSource) return false;
  const ref = typeof observation.ref === "string" ? observation.ref.trim() : "";
  if (ref.length < 8) return false;
  const topic = typeof observation.topic === "string" ? observation.topic.trim() : "";
  const nudge = typeof observation.nudge === "string" ? observation.nudge.trim() : "";
  if (!topic || !nudge) return false;
  return observation.dueAt instanceof Date && Number.isFinite(observation.dueAt.getTime());
}

/**
 * How long a subject stays "already said" after a suggestion about it fired.
 *
 * The open-trigger unique index alone is not enough: a stalled goal is still
 * stalled tomorrow, so without a cooldown the observer would raise the same
 * nudge on every sweep forever. A week is the point at which repeating
 * yourself stops being nagging and starts being useful again.
 */
const SUBJECT_COOLDOWN_DAYS = 7;

async function recentlySuggestedKeys(
  app: FastifyInstance,
  input: { userId: string; keys: string[]; now: Date },
): Promise<Set<string>> {
  if (input.keys.length === 0) return new Set();
  const since = new Date(input.now.getTime() - SUBJECT_COOLDOWN_DAYS * 24 * 3_600_000);
  const rows = await app.db
    .select({ dedupeKey: proactiveTriggers.dedupeKey })
    .from(proactiveTriggers)
    .where(
      and(
        eq(proactiveTriggers.userId, input.userId),
        inArray(proactiveTriggers.dedupeKey, input.keys),
        gte(proactiveTriggers.createdAt, since),
      ),
    );
  return new Set(
    rows
      .map((row) => row.dedupeKey)
      .filter((key): key is string => typeof key === "string"),
  );
}

async function countOpenSuggestions(
  app: FastifyInstance,
  userId: string,
): Promise<number> {
  const rows = await app.db
    .select({ value: count() })
    .from(proactiveTriggers)
    .where(
      and(
        eq(proactiveTriggers.userId, userId),
        eq(proactiveTriggers.createdBy, "observer"),
        inArray(proactiveTriggers.status, ["pending", "running"]),
      ),
    );
  return Number(rows[0]?.value ?? 0);
}

async function latestSessionId(
  app: FastifyInstance,
  userId: string,
): Promise<string | null> {
  const rows = await app.db
    .select({ id: chatSessions.id })
    .from(chatSessions)
    .where(eq(chatSessions.userId, userId))
    .orderBy(desc(chatSessions.lastMessageAt), desc(chatSessions.createdAt))
    .limit(1);
  return rows[0]?.id ?? null;
}

export async function collectObservations(
  app: FastifyInstance,
  input: { userId: string; now: Date; limit: number },
): Promise<ProactiveObservation[]> {
  const observations: ProactiveObservation[] = [];
  const { now } = input;

  const dueCutoff = new Date(now.getTime() + DUE_SOON_HOURS * 3_600_000);
  const dueGoals = await app.db
    .select({
      id: sessionGoals.id,
      sessionId: sessionGoals.sessionId,
      title: sessionGoals.title,
      dueAt: sessionGoals.dueAt,
    })
    .from(sessionGoals)
    .where(
      and(
        eq(sessionGoals.userId, input.userId),
        eq(sessionGoals.status, "active"),
        gte(sessionGoals.dueAt, now),
        lte(sessionGoals.dueAt, dueCutoff),
      ),
    )
    .orderBy(asc(sessionGoals.dueAt))
    .limit(input.limit);

  for (const goal of dueGoals) {
    observations.push({
      source: "goal_due_soon",
      ref: goal.id,
      sessionId: goal.sessionId,
      topic: compact(goal.title, 200),
      nudge: `"${compact(goal.title, 80)}" için tarih yaklaşıyor. Birlikte bitirelim mi?`,
      // Fire a few hours before, not at the deadline: a reminder that arrives
      // when it is already too late is just an accusation.
      dueAt: new Date(
        Math.max(now.getTime() + 30 * 60_000, (goal.dueAt?.getTime() ?? now.getTime()) - 6 * 3_600_000),
      ),
      sensitive: false,
    });
  }

  const stalledCutoff = new Date(now.getTime() - STALLED_GOAL_DAYS * 24 * 3_600_000);
  const stalledGoals = await app.db
    .select({
      id: sessionGoals.id,
      sessionId: sessionGoals.sessionId,
      title: sessionGoals.title,
      updatedAt: sessionGoals.updatedAt,
    })
    .from(sessionGoals)
    .where(
      and(
        eq(sessionGoals.userId, input.userId),
        eq(sessionGoals.status, "active"),
        lt(sessionGoals.updatedAt, stalledCutoff),
      ),
    )
    .orderBy(asc(sessionGoals.updatedAt))
    .limit(input.limit);

  for (const goal of stalledGoals) {
    observations.push({
      source: "goal_stalled",
      ref: goal.id,
      sessionId: goal.sessionId,
      topic: compact(goal.title, 200),
      nudge: `"${compact(goal.title, 80)}" bir süredir duruyor. Devam mı, kapatalım mı?`,
      dueAt: new Date(now.getTime() + 60 * 60_000),
      sensitive: false,
    });
  }

  const signalCutoff = new Date(now.getTime() - SIGNAL_FRESH_HOURS * 3_600_000);
  const signals = await app.db
    .select({
      id: worldSignals.id,
      sessionId: worldSignals.sessionId,
      kind: worldSignals.kind,
      summary: worldSignals.summary,
      confidenceBps: worldSignals.confidenceBps,
      privacy: worldSignals.privacy,
    })
    .from(worldSignals)
    .where(
      and(
        eq(worldSignals.userId, input.userId),
        gte(worldSignals.createdAt, signalCutoff),
        gte(worldSignals.confidenceBps, MIN_SIGNAL_CONFIDENCE_BPS),
      ),
    )
    .orderBy(desc(worldSignals.createdAt))
    .limit(input.limit);

  for (const signal of signals) {
    const summary = compact(signal.summary ?? "", 200);
    if (!summary) continue;
    const privacy =
      signal.privacy && typeof signal.privacy === "object"
        ? (signal.privacy as Record<string, unknown>)
        : {};
    const plaintextAllowed = privacy.backendPlaintextAllowed === true;
    observations.push({
      source: "world_signal",
      ref: signal.id,
      sessionId: signal.sessionId,
      topic: summary,
      nudge: plaintextAllowed
        ? `Şunu fark ettim: ${summary}. İşine yarar mı?`
        : "Bugünkü durumla ilgili bir şey fark ettim; bakmak ister misin?",
      dueAt: new Date(now.getTime() + 45 * 60_000),
      sensitive: !plaintextAllowed,
    });
  }

  return observations.filter(hasGroundedEvidence).slice(0, input.limit);
}

export async function createObserverTriggers(
  app: FastifyInstance,
  input: {
    userId: string;
    observations: ProactiveObservation[];
    now: Date;
    budget: number;
  },
): Promise<{ created: number; skipped: number }> {
  let created = 0;
  let skipped = 0;

  const cooling = await recentlySuggestedKeys(app, {
    userId: input.userId,
    keys: input.observations.map(observationDedupeKey),
    now: input.now,
  });

  for (const observation of input.observations) {
    if (created >= input.budget) {
      skipped += 1;
      continue;
    }
    if (cooling.has(observationDedupeKey(observation))) {
      // Said recently. Saying it again is how a helpful assistant becomes a
      // notification the user swipes away on reflex.
      skipped += 1;
      continue;
    }
    if (!observation.sessionId) {
      // Nowhere to land it. Better skipped than dropped into a synthetic
      // session the user has never seen.
      skipped += 1;
      continue;
    }

    const inserted = await app.db
      .insert(proactiveTriggers)
      .values({
        userId: input.userId,
        sessionId: observation.sessionId,
        kind: OBSERVER_TRIGGER_KIND,
        due: observation.dueAt,
        payload: {
          source: "turn_envelope",
          topic: observation.topic,
          nudge: observation.nudge,
          dueHint: observation.dueAt.toISOString(),
          // Traceability: the digest, the audit trail and any future review
          // can all get back to the row that caused this.
          evidence: { source: observation.source, ref: observation.ref },
          ...(observation.sensitive ? { privacy: "sensitive" } : {}),
        },
        status: "pending",
        createdBy: "observer",
        dedupeKey: observationDedupeKey(observation),
        updatedAt: input.now,
      })
      .onConflictDoNothing()
      .returning({ id: proactiveTriggers.id });

    if (!inserted[0]) {
      // The same subject is already queued — silence is the right answer.
      skipped += 1;
      continue;
    }

    created += 1;
    await recordProactiveEvent(app, {
      userId: input.userId,
      event: "created",
      kind: OBSERVER_TRIGGER_KIND,
      triggerId: inserted[0].id,
      source: "observer",
      reason: observation.source,
      detail: { ref: observation.ref, sensitive: observation.sensitive },
    });
  }

  return { created, skipped };
}

/**
 * Users the observer should look at. Same shape as the night watch scan: only
 * people with something observable, never a full table walk.
 */
export async function listObserverUserIds(
  app: FastifyInstance,
  limit: number,
): Promise<string[]> {
  const goalUsers = await app.db
    .selectDistinct({ userId: sessionGoals.userId })
    .from(sessionGoals)
    .where(eq(sessionGoals.status, "active"))
    .limit(limit);

  const ids = new Set(goalUsers.map((row) => row.userId));
  if (ids.size < limit) {
    const signalCutoff = new Date(Date.now() - SIGNAL_FRESH_HOURS * 3_600_000);
    const signalUsers = await app.db
      .selectDistinct({ userId: worldSignals.userId })
      .from(worldSignals)
      .where(gte(worldSignals.createdAt, signalCutoff))
      .limit(limit);
    for (const row of signalUsers) {
      if (ids.size >= limit) break;
      ids.add(row.userId);
    }
  }
  return [...ids];
}

const OBSERVER_USER_SCAN_LIMIT = 200;

export async function runProactiveObserverSweep(
  app: FastifyInstance,
  input: { now?: Date; userIds?: string[] } = {},
): Promise<ObserverSweepResult> {
  const result = emptyObserverSweep();
  if (app.config?.ELYAN_PROACTIVE_OBSERVER_ENABLED !== true) {
    return result;
  }

  const now = input.now ?? new Date();
  const userIds =
    input.userIds ?? (await listObserverUserIds(app, OBSERVER_USER_SCAN_LIMIT));

  for (const userId of userIds) {
    result.usersConsidered += 1;
    try {
      const policy = await readProactivePolicy(app, userId);
      // A user who turned proactivity off is not observed at all — not
      // observed-then-filtered. The difference matters: no rows are read on
      // their behalf.
      if (!policy.enabled) continue;
      if (policy.mutedKinds.includes(OBSERVER_TRIGGER_KIND)) continue;

      const open = await countOpenSuggestions(app, userId);
      const budget = Math.max(0, MAX_OPEN_SUGGESTIONS - open);
      if (budget === 0) continue;

      const observations = await collectObservations(app, {
        userId,
        now,
        limit: budget * 2,
      });
      if (observations.length === 0) continue;
      result.observed += observations.length;

      const fallbackSession = await latestSessionId(app, userId);
      const withSession = observations.map((observation) => ({
        ...observation,
        sessionId: observation.sessionId ?? fallbackSession,
      }));

      const outcome = await createObserverTriggers(app, {
        userId,
        observations: withSession,
        now,
        budget,
      });
      result.created += outcome.created;
      result.skipped += outcome.skipped;
    } catch (error) {
      app.log?.warn?.({ error, userId }, "proactive observer sweep failed for user");
    }
  }

  return result;
}
