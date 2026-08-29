import { and, eq, gte, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { proactiveEvents } from "../../db/schema.js";

/**
 * Proactive telemetry.
 *
 * The headline number is not delivery success — it is the **mute rate**. A
 * proactive assistant that gets silenced has failed even if every push landed,
 * so `summarizeProactiveHealth` reports muting next to firing and the two are
 * meant to be read together.
 *
 * Recording is best-effort by construction: a telemetry failure must never
 * take down the thing it is measuring.
 */

export type ProactiveEventName =
  | "created"
  | "fired"
  | "suppressed"
  | "push_sent"
  | "push_failed"
  | "push_skipped"
  | "opened"
  | "muted"
  | "unmuted"
  | "disabled"
  | "enabled"
  | "dismissed"
  | "track"
  | "snoozed"
  | "night_job_planned"
  | "night_job_settled";

export type RecordProactiveEventInput = {
  userId: string;
  event: ProactiveEventName;
  kind: string;
  triggerId?: string | null;
  /** `system` for engine-driven events, `user` for anything the user did. */
  source?: "system" | "user" | "observer" | "night_watch";
  reason?: string | null;
  detail?: Record<string, unknown>;
};

export async function recordProactiveEvent(
  app: FastifyInstance,
  input: RecordProactiveEventInput,
): Promise<void> {
  try {
    await app.db.insert(proactiveEvents).values({
      userId: input.userId,
      triggerId: input.triggerId ?? null,
      event: input.event,
      kind: input.kind.slice(0, 48),
      source: input.source ?? "system",
      reason: input.reason ? input.reason.slice(0, 120) : null,
      detail: input.detail ?? {},
    });
  } catch (error) {
    app.log?.debug?.(
      { error, event: input.event },
      "proactive event recording skipped",
    );
  }
}

export type ProactiveHealthSummary = {
  windowDays: number;
  created: number;
  fired: number;
  suppressed: number;
  pushSent: number;
  pushFailed: number;
  opened: number;
  muted: number;
  disabled: number;
  /**
   * muted / fired. Above ~0.2 the design is wrong, not the code: Elyan is
   * speaking when it should stay quiet.
   */
  muteRate: number;
  /** opened / pushSent. The only evidence a nudge was actually wanted. */
  openRate: number;
  suppressionReasons: Record<string, number>;
};

function ratio(numerator: number, denominator: number): number {
  if (denominator <= 0) return 0;
  return Math.round((numerator / denominator) * 1000) / 1000;
}

export async function summarizeProactiveHealth(
  app: FastifyInstance,
  input: { userId?: string; windowDays?: number; now?: Date } = {},
): Promise<ProactiveHealthSummary> {
  const windowDays = Math.max(1, Math.min(input.windowDays ?? 7, 90));
  const now = input.now ?? new Date();
  const since = new Date(now.getTime() - windowDays * 24 * 60 * 60_000);

  const filters = [gte(proactiveEvents.createdAt, since)];
  if (input.userId) {
    filters.push(eq(proactiveEvents.userId, input.userId));
  }

  const rows = await app.db
    .select({
      event: proactiveEvents.event,
      reason: proactiveEvents.reason,
      count: sql<number>`count(*)::int`,
    })
    .from(proactiveEvents)
    .where(and(...filters))
    .groupBy(proactiveEvents.event, proactiveEvents.reason);

  const totals = new Map<string, number>();
  const suppressionReasons: Record<string, number> = {};
  for (const row of rows) {
    const count = Number(row.count) || 0;
    totals.set(row.event, (totals.get(row.event) ?? 0) + count);
    if (row.event === "suppressed") {
      const reason = row.reason ?? "unknown";
      suppressionReasons[reason] = (suppressionReasons[reason] ?? 0) + count;
    }
  }

  const fired = totals.get("fired") ?? 0;
  const pushSent = totals.get("push_sent") ?? 0;
  const muted = totals.get("muted") ?? 0;
  const opened = totals.get("opened") ?? 0;

  return {
    windowDays,
    created: totals.get("created") ?? 0,
    fired,
    suppressed: totals.get("suppressed") ?? 0,
    pushSent,
    pushFailed: totals.get("push_failed") ?? 0,
    opened,
    muted,
    disabled: totals.get("disabled") ?? 0,
    muteRate: ratio(muted, fired),
    openRate: ratio(opened, pushSent),
    suppressionReasons,
  };
}
