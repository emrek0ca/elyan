import { randomUUID } from "node:crypto";
import { and, asc, eq, lte, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import {
  chatMessages,
  chatSessions,
  proactiveTriggers,
  userProactivePrefs,
} from "../../db/schema.js";
import type { TurnEnvelope } from "./turn-envelope.js";

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

export async function applyTurnProactiveOps(
  app: FastifyInstance,
  input: { userId: string; envelope: TurnEnvelope | null | undefined },
): Promise<number> {
  const ops = input.envelope?.proactive_ops ?? [];
  if (ops.length === 0) return 0;
  const existing = await readProactivePolicy(app, input.userId);
  let next: ProactivePolicy = { ...existing, mutedKinds: [...existing.mutedKinds] };
  for (const op of ops) {
    if (op.op === "enable") next.enabled = true;
    if (op.op === "disable") next.enabled = false;
    if (op.op === "mute" && op.kind && !next.mutedKinds.includes(op.kind)) next.mutedKinds.push(op.kind);
    if (op.op === "unmute" && op.kind) next.mutedKinds = next.mutedKinds.filter((kind) => kind !== op.kind);
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
  if (input.firedToday >= Math.max(0, policy.maxDaily)) return { allowed: false, reason: "daily_limit" };
  const hour = localHour(input.now ?? new Date(), policy.timezone);
  const quiet = policy.quietStartHour === policy.quietEndHour
    ? false
    : policy.quietStartHour < policy.quietEndHour
      ? hour >= policy.quietStartHour && hour < policy.quietEndHour
      : hour >= policy.quietStartHour || hour < policy.quietEndHour;
  return quiet ? { allowed: false, reason: "quiet_hours" } : { allowed: true };
}

async function readProactivePolicy(app: FastifyInstance, userId: string): Promise<ProactivePolicy> {
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
    result.created += 1;
  }
  return result;
}

function compactText(value: string, max: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1).trimEnd()}…`;
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

export async function publishProactiveAssistantMessage(
  app: FastifyInstance,
  input: {
    trigger: ProactiveTriggerRow;
    compose: ProactiveComposeResult;
    now?: Date;
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
    if (decision.reason === "quiet_hours") {
      await deferQuietHoursTrigger(app, trigger.id, now);
      return { status: "deferred", triggerId: trigger.id, reason: "quiet_hours" };
    }
    await markTrigger(app, {
      triggerId: trigger.id,
      status: "expired",
      now,
      reason: decision.reason,
    });
    return { status: "expired", triggerId: trigger.id, reason: decision.reason };
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
    if (decision.reason === "quiet_hours") {
      await deferQuietHoursTrigger(app, trigger.id, now);
      return { status: "deferred", triggerId: trigger.id, reason: "quiet_hours" };
    }
    await markTrigger(app, {
      triggerId: trigger.id,
      status: "expired",
      now,
      reason: decision.reason,
    });
    return { status: "expired", triggerId: trigger.id, reason: decision.reason };
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
