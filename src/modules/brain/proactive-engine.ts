import { createHash, randomUUID } from "node:crypto";
import { and, asc, eq, inArray, lte, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import {
  chatMessages,
  chatSessions,
  proactiveTriggers,
  userProactivePrefs,
} from "../../db/schema.js";
import { sendUserPush } from "../notifications/push-sender.js";
import { recordProactiveEvent } from "./proactive-metrics.js";
import type { TurnEnvelope } from "./turn-envelope.js";
import { foldTurkishDiacritics, truncateText as compactText } from "../../lib/text.js";

type FollowUp = TurnEnvelope["follow_ups"][number];

const uuidSchema = z.string().uuid();

export const proactiveTriggerPayloadSchema = z
  .object({
    source: z.literal("turn_envelope").default("turn_envelope"),
    topic: z.string().trim().min(1).max(240),
    nudge: z.string().trim().min(1).max(500),
    dueHint: z.string().trim().min(1).max(160),
  })
  .strip();

export type RecordFollowUpsResult = {
  processed: number;
  created: number;
  skipped: number;
};

type DeterministicFollowUpCapture = {
  kind: "explicit" | "candidate";
  triggerId: string;
  revision: number;
  block: Record<string, unknown> | null;
};

export function classifyDeterministicFollowUp(message: string, now = new Date()): { kind: "explicit" | "candidate"; topic: string; due: Date } | null {
  const text = message.trim().replace(/\s+/g, " ");
  const folded = foldTurkishDiacritics(text);
  const explicit = /(hatirlat|takip et|sonucunu sor|yarin .* sor|devam etmemizi hatirlat)/.test(folded);
  const candidate = /(bunu|sunu|konuyu).{0,40}(sonra|daha sonra).{0,30}(ele al|bak|don|devam)/.test(folded);
  if (!explicit && !candidate) return null;
  const tomorrow = /(yarin|tomorrow)/.test(folded);
  const due = new Date(now.getTime() + (tomorrow ? 24 : 2) * 60 * 60_000);
  const topic = compactText(
    text
      .replace(/(?:yarın|yarin|tomorrow|hatırlat|hatirlat|takip et|sonucunu sor)/gi, "")
      .replace(/\s+/g, " ")
      .trim() || "Bu konu",
    240,
  );
  return { kind: explicit ? "explicit" : "candidate", topic, due };
}

export async function captureDeterministicFollowUp(
  app: FastifyInstance,
  input: { userId: string; sessionId?: string | null; message: string; now?: Date },
): Promise<DeterministicFollowUpCapture | null> {
  const now = input.now ?? new Date();
  const intent = classifyDeterministicFollowUp(input.message, now);
  const sessionId = safeSessionId(input.sessionId);
  if (!intent || !sessionId) return null;
  const subjectHash = createHash("sha256")
    .update(`${input.userId}:${sessionId}:${intent.topic.toLocaleLowerCase("tr-TR")}:${intent.due.toISOString().slice(0, 10)}`)
    .digest("hex")
    .slice(0, 32);
  const dedupeKey = `followup:${subjectHash}`;
  const existing = await app.db
    .select({ id: proactiveTriggers.id, updatedAt: proactiveTriggers.updatedAt, status: proactiveTriggers.status })
    .from(proactiveTriggers)
    .where(and(
      eq(proactiveTriggers.userId, input.userId),
      eq(proactiveTriggers.dedupeKey, dedupeKey),
      inArray(proactiveTriggers.status, ["candidate", "pending", "running", "fired", "canceled"]),
    ))
    .limit(1);
  if (existing[0]) return null;
  const question = `“${compactText(intent.topic, 100)}” konusunu takip edeyim mi?`;
  const rows = await app.db
    .insert(proactiveTriggers)
    .values({
      userId: input.userId,
      sessionId,
      kind: "follow_up",
      due: intent.due,
      status: intent.kind === "explicit" ? "pending" : "candidate",
      createdBy: intent.kind === "explicit" ? "user" : "model",
      dedupeKey,
      payload: {
        source: "turn_envelope",
        topic: intent.topic,
        nudge: intent.kind === "explicit" ? `${intent.topic} için takip zamanı.` : question,
        dueHint: intent.due.toISOString(),
        explicit: intent.kind === "explicit",
        privacy: "identifier_only_push",
      },
      updatedAt: now,
    })
    .returning({ id: proactiveTriggers.id, updatedAt: proactiveTriggers.updatedAt });
  const row = rows[0];
  if (!row) return null;
  return {
    kind: intent.kind,
    triggerId: row.id,
    revision: row.updatedAt.getTime(),
    block: intent.kind === "candidate"
      ? {
          type: "proactive_touch",
          blockId: `followup_${row.id}`,
          title: "Bunu takip edebilirim",
          body: question,
          triggerId: row.id,
          revision: row.updatedAt.getTime(),
          availableActions: ["track", "dismissed"],
        }
      : null,
  };
}

export async function applyTurnProactiveOps(
  app: FastifyInstance,
  input: { userId: string; envelope: TurnEnvelope | null | undefined },
): Promise<number> {
  const ops = input.envelope?.proactive_ops ?? [];
  if (ops.length === 0) return 0;
  const existing = await readProactivePolicy(app, input.userId);
  let next: ProactivePolicy = { ...existing, mutedKinds: [...existing.mutedKinds] };
  for (const op of ops) {
    // Muting is the signal that matters most, so it is recorded as a
    // first-class user event rather than inferred later from a prefs diff.
    if (op.op === "enable") {
      next.enabled = true;
      if (!existing.enabled) {
        await recordProactiveEvent(app, {
          userId: input.userId,
          event: "enabled",
          kind: "all",
          source: "user",
        });
      }
    }
    if (op.op === "disable") {
      next.enabled = false;
      if (existing.enabled) {
        await recordProactiveEvent(app, {
          userId: input.userId,
          event: "disabled",
          kind: "all",
          source: "user",
        });
      }
    }
    if (op.op === "mute" && op.kind && !next.mutedKinds.includes(op.kind)) {
      next.mutedKinds.push(op.kind);
      await recordProactiveEvent(app, {
        userId: input.userId,
        event: "muted",
        kind: op.kind,
        source: "user",
      });
    }
    if (op.op === "unmute" && op.kind) {
      const wasMuted = next.mutedKinds.includes(op.kind);
      next.mutedKinds = next.mutedKinds.filter((kind) => kind !== op.kind);
      if (wasMuted) {
        await recordProactiveEvent(app, {
          userId: input.userId,
          event: "unmuted",
          kind: op.kind,
          source: "user",
        });
      }
    }
    if (op.op === "set_daily_limit" && op.max_daily != null) next.maxDaily = op.max_daily;
    if (op.op === "set_quiet_hours" && op.quiet_start_hour != null && op.quiet_end_hour != null) {
      next.quietStartHour = op.quiet_start_hour;
      next.quietEndHour = op.quiet_end_hour;
      if (op.timezone) next.timezone = op.timezone;
    }
  }
  const now = new Date();
  await app.db.insert(userProactivePrefs).values({
    userId: input.userId,
    enabled: next.enabled,
    maxDaily: next.maxDaily,
    quietStartHour: next.quietStartHour,
    quietEndHour: next.quietEndHour,
    timezone: next.timezone,
    mutedKinds: next.mutedKinds.slice(0, 20),
    updatedAt: now,
  }).onConflictDoUpdate({
    target: userProactivePrefs.userId,
    set: {
      enabled: next.enabled,
      maxDaily: next.maxDaily,
      quietStartHour: next.quietStartHour,
      quietEndHour: next.quietEndHour,
      timezone: next.timezone,
      mutedKinds: next.mutedKinds.slice(0, 20),
      updatedAt: now,
    },
  });
  return ops.length;
}

export type ProactiveTriggerRow = typeof proactiveTriggers.$inferSelect;

export type ProactiveComposeResult = {
  text: string;
  blocks?: unknown[];
};

export type ProcessProactiveTriggerResult =
  | { status: "idle"; reason: "no_due_trigger" }
  | { status: "expired"; triggerId: string; reason: string }
  | { status: "deferred"; triggerId: string; reason: "quiet_hours" }
  | { status: "fired"; triggerId: string; messageId: string };

export type ProactiveTriggerSweepResult = {
  processed: number;
  fired: number;
  expired: number;
  deferred: number;
  failed: number;
};

export type ProactivePolicy = {
  enabled: boolean;
  maxDaily: number;
  quietStartHour: number;
  quietEndHour: number;
  timezone: string;
  mutedKinds: string[];
};

export type ProactivePolicyDecision =
  | { allowed: true }
  | { allowed: false; reason: "disabled" | "muted_kind" | "daily_limit" | "quiet_hours" };

/** Trigger kind carrying the night-watch report. See `night-watch.ts`. */
export const DIGEST_KIND = "morning_digest";

const DEFAULT_PROACTIVE_POLICY: ProactivePolicy = {
  enabled: true,
  maxDaily: 3,
  quietStartHour: 22,
  quietEndHour: 8,
  timezone: "Europe/Istanbul",
  mutedKinds: [],
};

function localHour(now: Date, timezone: string): number {
  try {
    const hour = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      hour: "2-digit",
      hourCycle: "h23",
    }).formatToParts(now).find((part) => part.type === "hour")?.value;
    const parsed = Number(hour);
    return Number.isInteger(parsed) ? parsed : now.getUTCHours();
  } catch {
    return now.getUTCHours();
  }
}

export function evaluateProactivePolicy(input: {
  policy?: Partial<ProactivePolicy> | null;
  kind: string;
  firedToday: number;
  now?: Date;
}): ProactivePolicyDecision {
  const policy = { ...DEFAULT_PROACTIVE_POLICY, ...(input.policy ?? {}) };
  if (!policy.enabled) return { allowed: false, reason: "disabled" };
  if (policy.mutedKinds.includes(input.kind)) return { allowed: false, reason: "muted_kind" };
  // The morning digest is a report on work already done on the user's behalf,
  // not a nudge competing for attention. Letting the daily cap swallow it
  // would mean Elyan worked all night and then said nothing. It still obeys
  // `enabled` and an explicit mute of this kind — the user can always say no.
  if (
    input.kind !== DIGEST_KIND &&
    input.firedToday >= Math.max(0, policy.maxDaily)
  ) {
    return { allowed: false, reason: "daily_limit" };
  }
  const hour = localHour(input.now ?? new Date(), policy.timezone);
  const quiet = policy.quietStartHour === policy.quietEndHour
    ? false
    : policy.quietStartHour < policy.quietEndHour
      ? hour >= policy.quietStartHour && hour < policy.quietEndHour
      : hour >= policy.quietStartHour || hour < policy.quietEndHour;
  return quiet ? { allowed: false, reason: "quiet_hours" } : { allowed: true };
}

export async function readProactivePolicy(app: FastifyInstance, userId: string): Promise<ProactivePolicy> {
  const rows = await app.db.select().from(userProactivePrefs).where(eq(userProactivePrefs.userId, userId)).limit(1);
  const row = rows[0];
  if (!row || typeof row.enabled !== "boolean") return DEFAULT_PROACTIVE_POLICY;
  return {
    enabled: row.enabled,
    maxDaily: Number.isInteger(row.maxDaily) ? row.maxDaily : DEFAULT_PROACTIVE_POLICY.maxDaily,
    quietStartHour: Number.isInteger(row.quietStartHour) ? row.quietStartHour : DEFAULT_PROACTIVE_POLICY.quietStartHour,
    quietEndHour: Number.isInteger(row.quietEndHour) ? row.quietEndHour : DEFAULT_PROACTIVE_POLICY.quietEndHour,
    timezone: typeof row.timezone === "string" && row.timezone ? row.timezone : DEFAULT_PROACTIVE_POLICY.timezone,
    mutedKinds: Array.isArray(row.mutedKinds) ? row.mutedKinds.map(String).slice(0, 20) : [],
  };
}

async function countFiredToday(app: FastifyInstance, userId: string, now: Date): Promise<number> {
  const start = new Date(now);
  start.setUTCHours(0, 0, 0, 0);
  const rows = await app.db.execute(sql`
    select count(*)::int as count from ${proactiveTriggers}
    where user_id = ${userId} and status = 'fired' and fired_at >= ${start}
  `);
  const result = Array.isArray(rows) ? rows : (rows as { rows?: unknown[] }).rows ?? [];
  return Number((result[0] as { count?: unknown } | undefined)?.count ?? 0);
}

const DEFAULT_PROACTIVE_TIMEZONE_OFFSET_MS = 3 * 60 * 60_000;

function atDefaultLocalHour(now: Date, dayOffset: number, hour: number): Date {
  const local = new Date(now.getTime() + DEFAULT_PROACTIVE_TIMEZONE_OFFSET_MS);
  return new Date(
    Date.UTC(
      local.getUTCFullYear(),
      local.getUTCMonth(),
      local.getUTCDate() + dayOffset,
      hour,
    ) - DEFAULT_PROACTIVE_TIMEZONE_OFFSET_MS,
  );
}

export function resolveFollowUpDue(due: FollowUp["due"], now = new Date()): Date {
  if (due === "next_turn") {
    return new Date(now.getTime() + 10 * 60_000);
  }
  if (due === "same_day") {
    const local = new Date(now.getTime() + DEFAULT_PROACTIVE_TIMEZONE_OFFSET_MS);
    const sameDay = atDefaultLocalHour(
      now,
      0,
      Math.min(21, Math.max(local.getUTCHours() + 2, 9)),
    );
    if (sameDay.getTime() <= now.getTime()) {
      return new Date(now.getTime() + 60 * 60_000);
    }
    return sameDay;
  }
  if (due === "tomorrow") {
    return atDefaultLocalHour(now, 1, 9);
  }
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(due);
  if (dateOnly) {
    const parsed = new Date(
      Date.UTC(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]), 9) -
        DEFAULT_PROACTIVE_TIMEZONE_OFFSET_MS,
    );
    if (parsed.getTime() > now.getTime()) return parsed;
  }
  const parsed = new Date(due);
  if (Number.isFinite(parsed.getTime()) && parsed.getTime() > now.getTime()) {
    return parsed;
  }
  return new Date(now.getTime() + 60 * 60_000);
}

function safeSessionId(sessionId: string | null | undefined): string | null {
  return sessionId && uuidSchema.safeParse(sessionId).success ? sessionId : null;
}

export async function recordTurnFollowUps(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId?: string | null;
    envelope: TurnEnvelope | null | undefined;
    now?: Date;
  },
): Promise<RecordFollowUpsResult> {
  const followUps = input.envelope?.follow_ups ?? [];
  const result: RecordFollowUpsResult = {
    processed: 0,
    created: 0,
    skipped: 0,
  };
  if (followUps.length === 0) return result;

  const now = input.now ?? new Date();
  const sessionId = safeSessionId(input.sessionId);
  for (const followUp of followUps) {
    result.processed += 1;
    const payload = proactiveTriggerPayloadSchema.safeParse({
      source: "turn_envelope",
      topic: followUp.topic,
      nudge: followUp.nudge,
      dueHint: followUp.due,
    });
    if (!payload.success) {
      result.skipped += 1;
      continue;
    }
    await app.db.insert(proactiveTriggers).values({
      userId: input.userId,
      sessionId,
      kind: "follow_up",
      due: resolveFollowUpDue(followUp.due, now),
      payload: payload.data,
      status: "pending",
      createdBy: "model",
      updatedAt: now,
    });
    await recordProactiveEvent(app, {
      userId: input.userId,
      event: "created",
      kind: "follow_up",
      detail: { topic: payload.data.topic },
    });
    result.created += 1;
  }
  return result;
}

function estimateTokens(value: string): number {
  return Math.max(1, Math.ceil(value.length / 4));
}

function readPayload(payload: unknown): z.output<typeof proactiveTriggerPayloadSchema> | null {
  const parsed = proactiveTriggerPayloadSchema.safeParse(payload);
  return parsed.success ? parsed.data : null;
}

function readPayloadString(payload: unknown, key: "nudge" | "topic"): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "string" && value.trim() ? compactText(value, key === "nudge" ? 500 : 240) : null;
}

function buildAssistantPayload(input: {
  id: string;
  sessionId: string;
  userId: string;
  content: string;
  blocks: unknown[];
  createdAt: Date;
  updatedAt: Date;
}) {
  return {
    id: input.id,
    sessionId: input.sessionId,
    userId: input.userId,
    taskId: null,
    role: "assistant",
    status: "completed",
    content: input.content,
    metadata: {
      blocks: input.blocks,
    },
    createdAt: input.createdAt.toISOString(),
    updatedAt: input.updatedAt.toISOString(),
  };
}

export function buildProactiveComposePrompt(trigger: ProactiveTriggerRow): string {
  const payload = readPayload(trigger.payload);
  return [
    "Compose a short proactive Elyan follow-up message.",
    "Use a warm, concrete tone. Do not mention internal trigger IDs.",
    payload?.topic ? `Topic: ${payload.topic}` : null,
    payload?.nudge ? `Nudge: ${payload.nudge}` : null,
    `Due: ${trigger.due.toISOString()}`,
  ]
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

export function buildProactiveOpeningCompose(trigger: ProactiveTriggerRow): ProactiveComposeResult {
  const nudge = readPayloadString(trigger.payload, "nudge");
  const topic = readPayloadString(trigger.payload, "topic");
  const text = compactText(
    nudge ||
      (topic ? `${topic} için kaldığımız yerden devam etmek ister misin?` : "") ||
      "Kaldığımız yerden devam etmek ister misin?",
    500,
  );
  return { text };
}

export async function claimNextDueProactiveTrigger(
  app: FastifyInstance,
  input: { now?: Date } = {},
): Promise<ProactiveTriggerRow | null> {
  const now = input.now ?? new Date();
  const rows = await app.db
    .select()
    .from(proactiveTriggers)
    .where(and(eq(proactiveTriggers.status, "pending"), lte(proactiveTriggers.due, now)))
    .orderBy(asc(proactiveTriggers.due))
    .limit(1);
  const candidate = rows[0];
  if (!candidate) return null;

  const claimed = await app.db
    .update(proactiveTriggers)
    .set({
      status: "running",
      updatedAt: now,
    })
    .where(and(eq(proactiveTriggers.id, candidate.id), eq(proactiveTriggers.status, "pending")))
    .returning();
  return claimed[0] ?? null;
}

export async function claimDueProactiveTriggerForSession(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    now?: Date;
  },
): Promise<ProactiveTriggerRow | null> {
  const sessionId = safeSessionId(input.sessionId);
  if (!sessionId) return null;
  const now = input.now ?? new Date();
  const rows = await app.db
    .select()
    .from(proactiveTriggers)
    .where(and(
      eq(proactiveTriggers.userId, input.userId),
      eq(proactiveTriggers.sessionId, sessionId),
      eq(proactiveTriggers.status, "pending"),
      lte(proactiveTriggers.due, now),
    ))
    .orderBy(asc(proactiveTriggers.due))
    .limit(1);
  const candidate = rows[0];
  if (!candidate) return null;

  const claimed = await app.db
    .update(proactiveTriggers)
    .set({
      status: "running",
      updatedAt: now,
    })
    .where(and(
      eq(proactiveTriggers.id, candidate.id),
      eq(proactiveTriggers.status, "pending"),
    ))
    .returning();
  return claimed[0] ?? null;
}

async function markTrigger(
  app: FastifyInstance,
  input: {
    triggerId: string;
    status: "fired" | "expired" | "failed";
    now: Date;
    reason?: string;
  },
) {
  const update: Partial<typeof proactiveTriggers.$inferInsert> = {
    status: input.status,
    firedAt: input.status === "fired" ? input.now : null,
    canceledAt: input.status === "expired" ? input.now : null,
    updatedAt: input.now,
  };
  if (input.reason) {
    update.payload = sql`${proactiveTriggers.payload} || ${JSON.stringify({
      statusReason: input.reason,
    })}::jsonb` as never;
  }
  await app.db
    .update(proactiveTriggers)
    .set(update)
    .where(eq(proactiveTriggers.id, input.triggerId));
}

async function deferQuietHoursTrigger(
  app: FastifyInstance,
  triggerId: string,
  now: Date,
) {
  await app.db
    .update(proactiveTriggers)
    .set({
      status: "pending",
      due: new Date(now.getTime() + 60 * 60_000),
      updatedAt: now,
      payload: sql`${proactiveTriggers.payload} || ${JSON.stringify({
        statusReason: "quiet_hours",
      })}::jsonb` as never,
    })
    .where(eq(proactiveTriggers.id, triggerId));
}

/**
 * Notification title. Deliberately constant: the interesting part belongs in
 * the body, and a stable title is what makes iOS/Android group Elyan's
 * notifications together.
 */
const PROACTIVE_PUSH_TITLE = "Elyan";

/**
 * Shown instead of a preview when the trigger was derived from data the user
 * has not marked shareable. The message itself is unchanged in the app; only
 * the lock screen stays vague.
 */
const SENSITIVE_PUSH_BODY = "Sana bir önerim var.";

/**
 * A trigger the policy refused. Quiet hours only postpone; every other reason
 * retires the trigger. Both paths are recorded so the suppression mix is
 * visible — "we never speak because of the daily cap" and "we never speak
 * because everything is muted" are very different problems.
 */
async function settleDeniedProactiveTrigger(
  app: FastifyInstance,
  input: {
    trigger: ProactiveTriggerRow;
    reason: Exclude<ProactivePolicyDecision, { allowed: true }>["reason"];
    now: Date;
  },
): Promise<ProcessProactiveTriggerResult> {
  const { trigger, reason, now } = input;
  await recordProactiveEvent(app, {
    userId: trigger.userId,
    event: "suppressed",
    kind: trigger.kind,
    triggerId: trigger.id,
    reason,
  });

  if (reason === "quiet_hours") {
    await deferQuietHoursTrigger(app, trigger.id, now);
    return { status: "deferred", triggerId: trigger.id, reason: "quiet_hours" };
  }

  await markTrigger(app, {
    triggerId: trigger.id,
    status: "expired",
    now,
    reason,
  });
  return { status: "expired", triggerId: trigger.id, reason };
}

/**
 * Push carries a preview and ids, never the full message. See the contract in
 * `modules/notifications/push-sender.ts`.
 */
async function deliverProactivePush(
  app: FastifyInstance,
  input: {
    trigger: ProactiveTriggerRow;
    sessionId: string;
    messageId: string;
    content: string;
  },
): Promise<void> {
  const payload = input.trigger.payload && typeof input.trigger.payload === "object" && !Array.isArray(input.trigger.payload)
    ? input.trigger.payload as Record<string, unknown>
    : {};
  if (input.trigger.createdBy !== "user" && payload.explicit !== true) return;
  const result = await sendUserPush(app, {
    userId: input.trigger.userId,
    kind: `proactive.${input.trigger.kind}`,
    title: PROACTIVE_PUSH_TITLE,
    body: SENSITIVE_PUSH_BODY,
    collapseKey: `proactive:${input.sessionId}`,
    // `sessionId` alone is what the mobile deep-link parser needs to open the
    // right conversation; nothing else about the content travels.
    data: {
      sessionId: input.sessionId,
      triggerId: input.trigger.id,
    },
  }).catch((error) => {
    app.log.debug?.(
      { error, triggerId: input.trigger.id },
      "proactive push delivery threw",
    );
    return null;
  });

  if (!result) {
    await recordProactiveEvent(app, {
      userId: input.trigger.userId,
      event: "push_failed",
      kind: input.trigger.kind,
      triggerId: input.trigger.id,
      reason: "sender_threw",
    });
    return;
  }

  if (result.status === "sent") {
    await recordProactiveEvent(app, {
      userId: input.trigger.userId,
      event: "push_sent",
      kind: input.trigger.kind,
      triggerId: input.trigger.id,
      detail: { delivered: result.delivered, attempted: result.attempted },
    });
    return;
  }

  app.log.debug?.(
    { triggerId: input.trigger.id, status: result.status, reason: result.reason },
    "proactive push not delivered",
  );
  await recordProactiveEvent(app, {
    // "no push target" and "push not configured" are not failures of the
    // notification itself — the message still landed in the session.
    userId: input.trigger.userId,
    event: result.status === "failed" ? "push_failed" : "push_skipped",
    kind: input.trigger.kind,
    triggerId: input.trigger.id,
    reason: result.reason ?? result.status,
  });
}

export async function publishProactiveAssistantMessage(
  app: FastifyInstance,
  input: {
    trigger: ProactiveTriggerRow;
    compose: ProactiveComposeResult;
    now?: Date;
    /**
     * `false` when the user is demonstrably looking at this session right now
     * (the in-session path) — the SSE stream already delivered it and a push
     * would just buzz the phone in their hand.
     */
    notify?: boolean;
  },
): Promise<ProcessProactiveTriggerResult> {
  const now = input.now ?? new Date();
  if (!input.trigger.sessionId) {
    await markTrigger(app, {
      triggerId: input.trigger.id,
      status: "expired",
      now,
      reason: "missing_session",
    });
    return { status: "expired", triggerId: input.trigger.id, reason: "missing_session" };
  }

  const sessionRows = await app.db
    .select()
    .from(chatSessions)
    .where(and(eq(chatSessions.id, input.trigger.sessionId), eq(chatSessions.userId, input.trigger.userId)))
    .limit(1);
  const session = sessionRows[0];
  if (!session) {
    await markTrigger(app, {
      triggerId: input.trigger.id,
      status: "expired",
      now,
      reason: "session_not_found",
    });
    return { status: "expired", triggerId: input.trigger.id, reason: "session_not_found" };
  }

  const content = compactText(input.compose.text, 2_000);
  if (!content) {
    await markTrigger(app, {
      triggerId: input.trigger.id,
      status: "failed",
      now,
      reason: "empty_compose",
    });
    return { status: "expired", triggerId: input.trigger.id, reason: "empty_compose" };
  }

  const messageId = randomUUID();
  const blocks = input.compose.blocks?.slice(0, 12) ?? [];
  const messageRows = await app.db
    .insert(chatMessages)
    .values({
      id: messageId,
      sessionId: session.id,
      userId: input.trigger.userId,
      role: "assistant",
      status: "completed",
      content,
      preview: compactText(content, 320),
      tokenCount: estimateTokens(content),
      metadata: {
        proactive: {
          triggerId: input.trigger.id,
          kind: input.trigger.kind,
          createdBy: input.trigger.createdBy,
        },
        ...(blocks.length > 0 ? { blocks } : {}),
      },
      createdAt: now,
      updatedAt: now,
    })
    .returning();
  const message = messageRows[0];

  await app.db
    .update(chatSessions)
    .set({
      lastMessageAt: now,
      updatedAt: now,
      metadata: sql`${chatSessions.metadata} || ${JSON.stringify({
        proactiveLastTriggerId: input.trigger.id,
        proactiveLastMessageId: messageId,
      })}::jsonb` as never,
    })
    .where(eq(chatSessions.id, session.id));

  await markTrigger(app, {
    triggerId: input.trigger.id,
    status: "fired",
    now,
  });

  await recordProactiveEvent(app, {
    userId: input.trigger.userId,
    event: "fired",
    kind: input.trigger.kind,
    triggerId: input.trigger.id,
    source: input.trigger.createdBy === "observer" ? "observer" : "system",
    detail: { sessionId: session.id, notified: input.notify !== false },
  });

  const assistantMessage = buildAssistantPayload({
    id: message?.id ?? messageId,
    sessionId: session.id,
    userId: input.trigger.userId,
    content,
    blocks,
    createdAt: message?.createdAt ?? now,
    updatedAt: message?.updatedAt ?? now,
  });

  await app.services.eventBus.publish({
    topic: "chat.message.created",
    userId: input.trigger.userId,
    deviceId: session.targetDeviceId,
    payload: {
      sessionId: session.id,
      presentation: "chat",
      session: {
        id: session.id,
        title: session.title,
        status: session.status,
        source: session.source,
      },
      assistantMessage,
      dispatched: false,
      reused: false,
      proactive: {
        triggerId: input.trigger.id,
        kind: input.trigger.kind,
      },
    },
  }).catch((error) => {
    app.log.debug?.(
      {
        error: error instanceof Error ? error.message : "proactive_domain_event_publish_failed",
        triggerId: input.trigger.id,
        kind: input.trigger.kind,
      },
      "proactive chat domain event publish skipped",
    );
  });

  await app.services.eventBus.publishVolatile({
    topic: "message.created",
    userId: input.trigger.userId,
    deviceId: session.targetDeviceId,
    payload: {
      event: "message.created",
      taskId: null,
      sessionId: session.id,
      messageId,
      assistantMessageId: messageId,
      seq: 0,
      timestamp: now.toISOString(),
      presentation: "chat",
      assistantMessage,
      proactive: {
        triggerId: input.trigger.id,
        kind: input.trigger.kind,
      },
    },
  });

  await app.services.eventBus.publishVolatile({
    topic: "message.completed",
    userId: input.trigger.userId,
    deviceId: session.targetDeviceId,
    payload: {
      event: "message.completed",
      taskId: null,
      sessionId: session.id,
      messageId,
      assistantMessageId: messageId,
      seq: 1,
      timestamp: now.toISOString(),
      presentation: "chat",
      content,
      blocks,
      assistantMessage,
      proactive: {
        triggerId: input.trigger.id,
        kind: input.trigger.kind,
      },
    },
  });

  if (input.notify !== false) {
    await deliverProactivePush(app, {
      trigger: input.trigger,
      sessionId: session.id,
      messageId,
      content,
    });
  }

  return { status: "fired", triggerId: input.trigger.id, messageId };
}

export async function processDueProactiveTriggerForSession(
  app: FastifyInstance,
  input: {
    userId: string;
    sessionId: string;
    now?: Date;
    compose?: (trigger: ProactiveTriggerRow) => Promise<ProactiveComposeResult>;
  },
): Promise<ProcessProactiveTriggerResult> {
  const now = input.now ?? new Date();
  const trigger = await claimDueProactiveTriggerForSession(app, {
    userId: input.userId,
    sessionId: input.sessionId,
    now,
  });
  if (!trigger) {
    return { status: "idle", reason: "no_due_trigger" };
  }
  const policy = await readProactivePolicy(app, trigger.userId).catch(() => DEFAULT_PROACTIVE_POLICY);
  const firedToday = await countFiredToday(app, trigger.userId, now).catch(() => 0);
  const decision = evaluateProactivePolicy({ policy, kind: trigger.kind, firedToday, now });
  if (!decision.allowed) {
    return settleDeniedProactiveTrigger(app, { trigger, reason: decision.reason, now });
  }
  const compose = await (input.compose ?? (async (item) => buildProactiveOpeningCompose(item)))(trigger).catch(async () => {
    await markTrigger(app, {
      triggerId: trigger.id,
      status: "failed",
      now,
      reason: "compose_failed",
    });
    return null;
  });
  if (!compose) {
    return { status: "expired", triggerId: trigger.id, reason: "compose_failed" };
  }
  return publishProactiveAssistantMessage(app, {
    trigger,
    compose,
    now,
    // In-session path: the user is on this screen, the stream already shows it.
    notify: false,
  });
}

export async function processNextDueProactiveTrigger(
  app: FastifyInstance,
  input: {
    now?: Date;
    compose: (trigger: ProactiveTriggerRow) => Promise<ProactiveComposeResult>;
  },
): Promise<ProcessProactiveTriggerResult> {
  const now = input.now ?? new Date();
  const trigger = await claimNextDueProactiveTrigger(app, { now });
  if (!trigger) {
    return { status: "idle", reason: "no_due_trigger" };
  }
  const policy = await readProactivePolicy(app, trigger.userId).catch(() => DEFAULT_PROACTIVE_POLICY);
  const firedToday = await countFiredToday(app, trigger.userId, now).catch(() => 0);
  const decision = evaluateProactivePolicy({ policy, kind: trigger.kind, firedToday, now });
  if (!decision.allowed) {
    return settleDeniedProactiveTrigger(app, { trigger, reason: decision.reason, now });
  }
  const compose = await input.compose(trigger).catch(async () => {
    await markTrigger(app, {
      triggerId: trigger.id,
      status: "failed",
      now,
      reason: "compose_failed",
    });
    return null;
  });
  if (!compose) {
    return { status: "expired", triggerId: trigger.id, reason: "compose_failed" };
  }
  return publishProactiveAssistantMessage(app, {
    trigger,
    compose,
    now,
  });
}

export async function sweepDueProactiveTriggers(
  app: FastifyInstance,
  input: {
    now?: Date;
    limit?: number;
    compose: (trigger: ProactiveTriggerRow) => Promise<ProactiveComposeResult>;
  },
): Promise<ProactiveTriggerSweepResult> {
  const limit = Math.max(1, Math.min(input.limit ?? 10, 50));
  const result: ProactiveTriggerSweepResult = {
    processed: 0,
    fired: 0,
    expired: 0,
    deferred: 0,
    failed: 0,
  };

  for (let index = 0; index < limit; index += 1) {
    const processed = await processNextDueProactiveTrigger(app, {
      now: input.now,
      compose: input.compose,
    });
    if (processed.status === "idle") break;
    result.processed += 1;
    if (processed.status === "fired") {
      result.fired += 1;
    } else if (processed.status === "deferred") {
      result.deferred += 1;
    } else if (processed.reason === "compose_failed" || processed.reason === "empty_compose") {
      result.failed += 1;
    } else {
      result.expired += 1;
    }
  }

  return result;
}
