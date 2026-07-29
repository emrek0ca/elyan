import { createHash, randomUUID } from "node:crypto";
import { and, asc, desc, eq, gt, inArray, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  devices,
  nightWatchJobs,
  proactiveTriggers,
  runtimeConnections,
  sessionGoals,
  tasks,
} from "../../db/schema.js";
import { createTask } from "../tasks/service.js";
import { DIGEST_KIND, readProactivePolicy } from "./proactive-engine.js";
import { recordProactiveEvent } from "./proactive-metrics.js";

/**
 * Night watch — Elyan working while the user sleeps.
 *
 * Three rules shape everything here:
 *
 * 1. **Quiet hours silence notifications, not work.** The user's night is when
 *    the desktop is free; it is the best time to run, and the worst time to
 *    buzz. So the work runs now and exactly one digest goes out in the morning.
 * 2. **Nothing with an outward or destructive side effect runs unattended.**
 *    Capabilities are allowlisted here and again as a route decision, so a
 *    planner cannot widen them. Anything that would need approval is left for
 *    the morning as a decision, not executed.
 * 3. **No job without evidence.** Every job records what observation caused it.
 *    A job Elyan cannot justify is the same fabrication failure the
 *    `resolvedTarget` gate exists to prevent.
 */

/**
 * Read-mostly capabilities. Document/chart/sheet writers are included because
 * they only ever create new files in Elyan's own output folder — that is how a
 * finished report exists in the morning. Anything that can overwrite a path,
 * send a message, drive the screen, or mutate memory is absent on purpose.
 */
export const NIGHT_WATCH_ALLOWED_CAPABILITIES: readonly string[] = [
  "web_research",
  "retrieve_context",
  "file_read",
  "file_search",
  "directory_tree",
  "document_read",
  "get_calendar_events",
  "get_reminders",
  "get_weather",
  "data_analyze",
  "text_analyze",
  "math_solve",
  "image_read",
  "ocr_read",
  "git_status",
  "git_diff",
  "sys_info",
  "document_write",
  "spreadsheet_write",
  "chart_generate",
];

const ALLOWED_CAPABILITY_SET = new Set(NIGHT_WATCH_ALLOWED_CAPABILITIES);

/** Heartbeat freshness required before we believe a desktop can take work. */
const DESKTOP_FRESH_MS = 5 * 60_000;
const MAX_PROMPT_LENGTH = 1_200;
const DIGEST_MAX_LINES = 8;

export type NightWatchEvidence = {
  /** What kind of observation produced this job. */
  source: "session_goal" | "follow_up_trigger";
  /** Primary key of the observed row — the job is traceable back to it. */
  ref: string;
  note: string;
};

export type NightWatchCandidate = {
  title: string;
  prompt: string;
  capabilities: string[];
  evidence: NightWatchEvidence;
  sessionId: string | null;
};

export type NightWatchPlanResult = {
  status: "planned" | "skipped";
  reason?:
    | "disabled"
    | "outside_night_window"
    | "no_desktop"
    | "no_candidates"
    | "already_planned"
    | "budget_exhausted";
  planned: number;
  dispatched: number;
};

export type NightWatchJobRow = typeof nightWatchJobs.$inferSelect;

export function isNightWatchCapabilityAllowed(capability: string): boolean {
  return ALLOWED_CAPABILITY_SET.has(capability);
}

/**
 * Fail-closed: unknown capabilities are dropped rather than passed through,
 * and a candidate left with nothing runnable is rejected by the caller.
 */
export function sanitizeNightWatchCapabilities(
  capabilities: readonly string[],
): string[] {
  const seen = new Set<string>();
  for (const capability of capabilities) {
    const normalized = String(capability ?? "").trim();
    if (normalized && isNightWatchCapabilityAllowed(normalized)) {
      seen.add(normalized);
    }
  }
  return [...seen];
}

export function nightWatchFingerprint(input: {
  source: string;
  ref: string;
  prompt: string;
}): string {
  return createHash("sha256")
    .update(`${input.source}|${input.ref}|${input.prompt.trim().toLowerCase()}`)
    .digest("hex")
    .slice(0, 64);
}

function localParts(now: Date, timezone: string): { date: string; hour: number } {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hourCycle: "h23",
    }).formatToParts(now);
    const read = (type: string) =>
      parts.find((part) => part.type === type)?.value ?? "";
    const date = `${read("year")}-${read("month")}-${read("day")}`;
    const hour = Number(read("hour"));
    return {
      date: /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : now.toISOString().slice(0, 10),
      hour: Number.isInteger(hour) ? hour : now.getUTCHours(),
    };
  } catch {
    return { date: now.toISOString().slice(0, 10), hour: now.getUTCHours() };
  }
}

export function localHourIn(now: Date, timezone: string): number {
  return localParts(now, timezone).hour;
}

/**
 * The night is labelled by the date it *started*, so work done at 02:00 and
 * the digest sent at 08:00 the same morning belong to one night.
 */
export function nightDateKey(
  now: Date,
  timezone: string,
  quietStartHour: number,
): string {
  const { date, hour } = localParts(now, timezone);
  if (hour >= quietStartHour) {
    return date;
  }
  const previous = new Date(`${date}T00:00:00Z`);
  previous.setUTCDate(previous.getUTCDate() - 1);
  return previous.toISOString().slice(0, 10);
}

/**
 * Whether the user's quiet window is currently open. Wraps midnight when
 * `quietStartHour > quietEndHour`, which is the normal 22→08 case.
 */
export function isWithinNightWindow(
  hour: number,
  quietStartHour: number,
  quietEndHour: number,
): boolean {
  if (quietStartHour === quietEndHour) return false;
  return quietStartHour < quietEndHour
    ? hour >= quietStartHour && hour < quietEndHour
    : hour >= quietStartHour || hour < quietEndHour;
}

/**
 * A desktop that can actually take work right now. Deliberately reads the DB
 * heartbeat rather than the in-process WebSocket hub: the scheduler runs in a
 * separate container and has no hub of its own.
 */
export async function findNightWatchDesktop(
  app: FastifyInstance,
  userId: string,
  now: Date,
): Promise<{ deviceId: string } | null> {
  const cutoff = new Date(now.getTime() - DESKTOP_FRESH_MS);
  const rows = await app.db
    .select({ deviceId: devices.id, lastHeartbeatAt: runtimeConnections.lastHeartbeatAt })
    .from(devices)
    .innerJoin(runtimeConnections, eq(runtimeConnections.deviceId, devices.id))
    .where(
      and(
        eq(devices.userId, userId),
        eq(devices.type, "desktop"),
        eq(devices.isActive, true),
        gt(runtimeConnections.lastHeartbeatAt, cutoff),
      ),
    )
    .orderBy(desc(runtimeConnections.lastHeartbeatAt))
    .limit(1);
  const row = rows[0];
  return row ? { deviceId: row.deviceId } : null;
}

function compact(value: string, max: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1)}…`;
}

/**
 * Candidate work, derived only from things the user already committed to.
 *
 * Note what is *not* here: nothing is invented from general interest,
 * browsing history or inferred mood. If the user never expressed it, Elyan
 * does not spend their night on it.
 */
export async function collectNightWatchCandidates(
  app: FastifyInstance,
  input: { userId: string; limit: number },
): Promise<NightWatchCandidate[]> {
  const candidates: NightWatchCandidate[] = [];

  const goals = await app.db
    .select({
      id: sessionGoals.id,
      sessionId: sessionGoals.sessionId,
      title: sessionGoals.title,
      description: sessionGoals.description,
      dueAt: sessionGoals.dueAt,
    })
    .from(sessionGoals)
    .where(and(eq(sessionGoals.userId, input.userId), eq(sessionGoals.status, "active")))
    .orderBy(asc(sessionGoals.dueAt), desc(sessionGoals.updatedAt))
    .limit(input.limit * 2);

  for (const goal of goals) {
    const description = goal.description?.trim() ?? "";
    // A goal with no description is a label, not an instruction — running it
    // would mean guessing what the user meant.
    if (!description) continue;
    candidates.push({
      title: compact(goal.title, 200),
      prompt: compact(
        [
          "Bu hedef için gece boyunca hazırlık yap. Yalnızca oku, araştır ve",
          "sonucu bir özet/rapor olarak hazırla; hiçbir şey gönderme, silme veya değiştirme.",
          `Hedef: ${goal.title}`,
          `Ayrıntı: ${description}`,
        ].join("\n"),
        MAX_PROMPT_LENGTH,
      ),
      capabilities: ["web_research", "retrieve_context", "document_write"],
      evidence: {
        source: "session_goal",
        ref: goal.id,
        note: compact(goal.title, 160),
      },
      sessionId: goal.sessionId,
    });
  }

  if (candidates.length < input.limit) {
    const pending = await app.db
      .select({
        id: proactiveTriggers.id,
        sessionId: proactiveTriggers.sessionId,
        payload: proactiveTriggers.payload,
      })
      .from(proactiveTriggers)
      .where(
        and(
          eq(proactiveTriggers.userId, input.userId),
          eq(proactiveTriggers.status, "pending"),
          eq(proactiveTriggers.kind, "follow_up"),
        ),
      )
      .orderBy(asc(proactiveTriggers.due))
      .limit(input.limit * 2);

    for (const trigger of pending) {
      const payload =
        trigger.payload && typeof trigger.payload === "object"
          ? (trigger.payload as Record<string, unknown>)
          : {};
      const topic = typeof payload.topic === "string" ? payload.topic.trim() : "";
      const nudge = typeof payload.nudge === "string" ? payload.nudge.trim() : "";
      if (!topic) continue;
      candidates.push({
        title: compact(topic, 200),
        prompt: compact(
          [
            "Bu konu için gece boyunca ön hazırlık yap: araştır, topla, özetle.",
            "Hiçbir şey gönderme, silme veya değiştirme.",
            `Konu: ${topic}`,
            nudge ? `Not: ${nudge}` : "",
          ]
            .filter(Boolean)
            .join("\n"),
          MAX_PROMPT_LENGTH,
        ),
        capabilities: ["web_research", "retrieve_context"],
        evidence: {
          source: "follow_up_trigger",
          ref: trigger.id,
          note: compact(topic, 160),
        },
        sessionId: trigger.sessionId,
      });
    }
  }

  return candidates.slice(0, input.limit);
}

/**
 * The route decision is supplied rather than inferred. Letting the router
 * decide would mean a model gets to choose, at 03:00 with nobody watching,
 * whether this task needs approval.
 */
function buildNightWatchRouteDecision(capabilities: string[]) {
  return {
    route: "desktop_task",
    mode: "task",
    capabilities,
    privacyClass: "private_desktop",
    requiresApproval: false,
    reason: "night_watch_read_only",
    intent: "desktop_task",
    confidence: 1,
    requiredRuntime: "desktop",
    privacyLevel: "medium",
    shouldAskClarification: false,
    failClosedReason: null,
    selectedWorkload: "desktop_task",
    taskRoute: {
      target: "desktop_runtime",
      operationalRoute: "desktop_runtime",
      executionPlan: ["desktop_runtime"],
      reason: "night_watch_read_only",
      needsDesktop: true,
      needsPrivateDesktopData: true,
      needsUserApproval: false,
      requiredCapabilities: capabilities,
    },
  };
}

export async function planNightWatch(
  app: FastifyInstance,
  input: {
    userId: string;
    now: Date;
    timezone: string;
    quietStartHour: number;
    quietEndHour: number;
  },
): Promise<NightWatchPlanResult> {
  const empty = { planned: 0, dispatched: 0 };
  if (app.config?.ELYAN_NIGHT_WATCH_ENABLED !== true) {
    return { status: "skipped", reason: "disabled", ...empty };
  }

  // The whole premise is that the user is asleep and the machine is free.
  // Outside the quiet window that premise is false, so refuse regardless of
  // how this was called.
  if (
    !isWithinNightWindow(
      localHourIn(input.now, input.timezone),
      input.quietStartHour,
      input.quietEndHour,
    )
  ) {
    return { status: "skipped", reason: "outside_night_window", ...empty };
  }

  const budget = Math.max(0, app.config?.ELYAN_NIGHT_WATCH_MAX_JOBS_PER_NIGHT ?? 0);
  if (budget === 0) {
    return { status: "skipped", reason: "budget_exhausted", ...empty };
  }

  const nightDate = nightDateKey(input.now, input.timezone, input.quietStartHour);

  const existing = await app.db
    .select({ id: nightWatchJobs.id })
    .from(nightWatchJobs)
    .where(
      and(eq(nightWatchJobs.userId, input.userId), eq(nightWatchJobs.nightDate, nightDate)),
    )
    .limit(1);
  if (existing.length > 0) {
    return { status: "skipped", reason: "already_planned", ...empty };
  }

  const desktop = await findNightWatchDesktop(app, input.userId, input.now);
  if (!desktop) {
    // Honest outcome, not a silent no-op: with no desktop awake there is no
    // machine to work on, and the morning digest should say so rather than
    // imply Elyan chose to rest.
    return { status: "skipped", reason: "no_desktop", ...empty };
  }

  const candidates = await collectNightWatchCandidates(app, {
    userId: input.userId,
    limit: budget,
  });
  if (candidates.length === 0) {
    return { status: "skipped", reason: "no_candidates", ...empty };
  }

  let planned = 0;
  let dispatched = 0;

  for (const candidate of candidates) {
    const capabilities = sanitizeNightWatchCapabilities(candidate.capabilities);
    if (capabilities.length === 0) continue;

    const fingerprint = nightWatchFingerprint({
      source: candidate.evidence.source,
      ref: candidate.evidence.ref,
      prompt: candidate.prompt,
    });

    const inserted = await app.db
      .insert(nightWatchJobs)
      .values({
        userId: input.userId,
        nightDate,
        deviceId: desktop.deviceId,
        sessionId: candidate.sessionId,
        title: candidate.title,
        prompt: candidate.prompt,
        capabilities,
        evidence: candidate.evidence,
        fingerprint,
        status: "planned",
      })
      .onConflictDoNothing()
      .returning({ id: nightWatchJobs.id });

    const job = inserted[0];
    if (!job) continue;
    planned += 1;

    await recordProactiveEvent(app, {
      userId: input.userId,
      event: "night_job_planned",
      kind: "night_work",
      source: "night_watch",
      detail: {
        jobId: job.id,
        evidenceSource: candidate.evidence.source,
        capabilities,
      },
    });

    const ok = await dispatchNightWatchJob(app, {
      jobId: job.id,
      userId: input.userId,
      deviceId: desktop.deviceId,
      title: candidate.title,
      prompt: candidate.prompt,
      capabilities,
      evidence: candidate.evidence,
      now: input.now,
    });
    if (ok) dispatched += 1;
  }

  if (planned === 0) {
    return { status: "skipped", reason: "no_candidates", ...empty };
  }
  return { status: "planned", planned, dispatched };
}

async function dispatchNightWatchJob(
  app: FastifyInstance,
  input: {
    jobId: string;
    userId: string;
    deviceId: string;
    title: string;
    prompt: string;
    capabilities: string[];
    evidence: NightWatchEvidence;
    now: Date;
  },
): Promise<boolean> {
  try {
    const result = await createTask(app, {
      userId: input.userId,
      targetDeviceId: input.deviceId,
      title: input.title,
      payload: {
        prompt: input.prompt,
        source: "desktop",
        metadata: {
          channel: "night_watch",
          routeDecision: buildNightWatchRouteDecision(input.capabilities),
          // The desktop runtime reads this to keep itself inside the
          // unattended envelope even if a planner suggests otherwise.
          autonomy: {
            mode: "night_watch",
            jobId: input.jobId,
            unattended: true,
            allowedCapabilities: input.capabilities,
            evidence: input.evidence,
          },
        },
      },
      requestedCapabilities: input.capabilities,
      requestedCapabilitiesResolved: true,
      requestId: randomUUID(),
      idempotencyKey: `night_watch:${input.jobId}`,
    });

    const taskId = result?.task?.id ?? null;
    await app.db
      .update(nightWatchJobs)
      .set({
        taskId,
        status: taskId ? "dispatched" : "failed",
        statusReason: taskId ? null : "task_not_created",
        dispatchedAt: input.now,
        updatedAt: input.now,
      })
      .where(eq(nightWatchJobs.id, input.jobId));
    return Boolean(taskId);
  } catch (error) {
    app.log?.warn?.({ error, jobId: input.jobId }, "night watch dispatch failed");
    await app.db
      .update(nightWatchJobs)
      .set({
        status: "failed",
        statusReason: "dispatch_error",
        settledAt: input.now,
        updatedAt: input.now,
      })
      .where(eq(nightWatchJobs.id, input.jobId))
      .catch(() => undefined);
    return false;
  }
}

const TASK_STATUS_TO_JOB_STATUS: Record<string, string> = {
  completed: "completed",
  failed: "failed",
  canceled: "skipped",
  waiting_approval: "needs_approval",
};

/**
 * Fold task outcomes back into the job rows. Runs before the digest so the
 * digest reads settled facts instead of chasing task state itself.
 */
export async function settleNightWatchJobs(
  app: FastifyInstance,
  input: { userId: string; nightDate: string; now: Date },
): Promise<number> {
  const open = await app.db
    .select({
      id: nightWatchJobs.id,
      taskId: nightWatchJobs.taskId,
    })
    .from(nightWatchJobs)
    .where(
      and(
        eq(nightWatchJobs.userId, input.userId),
        eq(nightWatchJobs.nightDate, input.nightDate),
        inArray(nightWatchJobs.status, ["planned", "dispatched"]),
      ),
    );

  const withTasks = open.filter(
    (job): job is { id: string; taskId: string } => Boolean(job.taskId),
  );
  if (withTasks.length === 0) return 0;

  const taskRows = await app.db
    .select({
      id: tasks.id,
      status: tasks.status,
      summary: tasks.summary,
      error: tasks.error,
    })
    .from(tasks)
    .where(inArray(tasks.id, withTasks.map((job) => job.taskId)));

  const byTaskId = new Map(taskRows.map((row) => [row.id, row]));
  let settled = 0;

  for (const job of withTasks) {
    const task = byTaskId.get(job.taskId);
    if (!task) continue;
    const nextStatus = TASK_STATUS_TO_JOB_STATUS[task.status];
    if (!nextStatus) continue;

    await app.db
      .update(nightWatchJobs)
      .set({
        status: nextStatus,
        resultSummary: compact(task.summary ?? task.error ?? "", 600) || null,
        settledAt: input.now,
        updatedAt: input.now,
      })
      .where(eq(nightWatchJobs.id, job.id));
    settled += 1;

    await recordProactiveEvent(app, {
      userId: input.userId,
      event: "night_job_settled",
      kind: "night_work",
      source: "night_watch",
      reason: nextStatus,
      detail: { jobId: job.id, taskId: job.taskId },
    });
  }

  return settled;
}

export async function listNightWatchJobs(
  app: FastifyInstance,
  input: { userId: string; nightDate: string },
): Promise<NightWatchJobRow[]> {
  return app.db
    .select()
    .from(nightWatchJobs)
    .where(
      and(
        eq(nightWatchJobs.userId, input.userId),
        eq(nightWatchJobs.nightDate, input.nightDate),
      ),
    )
    .orderBy(asc(nightWatchJobs.createdAt));
}

export type MorningDigest = { text: string; jobIds: string[]; hasWork: boolean };

/**
 * The digest is assembled from rows, not generated by a model.
 *
 * This is the whole point: a summary of unattended work is exactly where a
 * fluent-sounding invention would be most damaging and least detectable. If a
 * job produced no summary the digest says so instead of filling the gap.
 */
export function buildMorningDigest(jobs: NightWatchJobRow[]): MorningDigest {
  const completed = jobs.filter((job) => job.status === "completed");
  const needsApproval = jobs.filter((job) => job.status === "needs_approval");
  const failed = jobs.filter((job) => job.status === "failed");

  if (jobs.length === 0) {
    return { text: "", jobIds: [], hasWork: false };
  }

  const lines: string[] = [];
  const headline: string[] = [];
  if (completed.length > 0) headline.push(`${completed.length} iş bitti`);
  if (needsApproval.length > 0) headline.push(`${needsApproval.length} onayını bekliyor`);
  if (failed.length > 0) headline.push(`${failed.length} yarım kaldı`);
  if (headline.length === 0) {
    headline.push("gece başlattığım işler hâlâ sürüyor");
  }
  lines.push(`Gece çalıştım: ${headline.join(", ")}.`);

  for (const job of [...completed, ...needsApproval, ...failed].slice(0, DIGEST_MAX_LINES)) {
    const marker =
      job.status === "completed" ? "✓" : job.status === "needs_approval" ? "•" : "×";
    const detail = job.resultSummary?.trim();
    const suffix =
      job.status === "needs_approval"
        ? " — onayını bekliyor"
        : detail
          ? ` — ${compact(detail, 180)}`
          : job.status === "completed"
            ? " — çıktı hazır, detayını açınca görürsün"
            : "";
    lines.push(`${marker} ${compact(job.title, 120)}${suffix}`);
  }

  return {
    text: lines.join("\n"),
    jobIds: jobs.map((job) => job.id),
    hasWork: true,
  };
}

/**
 * Queue the digest as an ordinary proactive trigger so it inherits the whole
 * existing path: policy check, compose, publish, push, telemetry.
 */
export async function scheduleMorningDigest(
  app: FastifyInstance,
  input: {
    userId: string;
    nightDate: string;
    sessionId: string | null;
    due: Date;
    now: Date;
  },
): Promise<{ status: "scheduled" | "skipped"; reason?: string }> {
  if (!input.sessionId) {
    return { status: "skipped", reason: "no_session" };
  }

  const dedupeKey = `morning_digest:${input.nightDate}`;

  // The unique index only covers triggers that are still open, so it stops
  // concurrent inserts but not a second one after the first has fired. The
  // digest hour lasts an hour and this sweep runs every 30 seconds — without
  // this check the user would get the same digest ~120 times.
  const alreadySent = await app.db
    .select({ id: proactiveTriggers.id })
    .from(proactiveTriggers)
    .where(
      and(
        eq(proactiveTriggers.userId, input.userId),
        eq(proactiveTriggers.dedupeKey, dedupeKey),
      ),
    )
    .limit(1);
  if (alreadySent.length > 0) {
    return { status: "skipped", reason: "already_scheduled" };
  }

  const inserted = await app.db
    .insert(proactiveTriggers)
    .values({
      userId: input.userId,
      sessionId: input.sessionId,
      kind: DIGEST_KIND,
      due: input.due,
      payload: { source: "night_watch", nightDate: input.nightDate },
      status: "pending",
      createdBy: "night_watch",
      dedupeKey,
      updatedAt: input.now,
    })
    .onConflictDoNothing()
    .returning({ id: proactiveTriggers.id });

  if (!inserted[0]) {
    return { status: "skipped", reason: "already_scheduled" };
  }

  await recordProactiveEvent(app, {
    userId: input.userId,
    event: "created",
    kind: DIGEST_KIND,
    triggerId: inserted[0].id,
    source: "night_watch",
    detail: { nightDate: input.nightDate },
  });

  return { status: "scheduled" };
}

/**
 * Session the digest lands in: the most recently touched conversation. The
 * digest is a continuation of the relationship, not a new inbox.
 */
export async function resolveDigestSessionId(
  app: FastifyInstance,
  input: { userId: string; nightDate: string },
): Promise<string | null> {
  const fromJobs = await app.db
    .select({ sessionId: nightWatchJobs.sessionId })
    .from(nightWatchJobs)
    .where(
      and(
        eq(nightWatchJobs.userId, input.userId),
        eq(nightWatchJobs.nightDate, input.nightDate),
        sql`${nightWatchJobs.sessionId} is not null`,
      ),
    )
    .orderBy(desc(nightWatchJobs.createdAt))
    .limit(1);
  return fromJobs[0]?.sessionId ?? null;
}

export type NightWatchSweepResult = {
  planned: number;
  dispatched: number;
  settled: number;
  digestsScheduled: number;
  usersConsidered: number;
};

export function emptyNightWatchSweep(): NightWatchSweepResult {
  return {
    planned: 0,
    dispatched: 0,
    settled: 0,
    digestsScheduled: 0,
    usersConsidered: 0,
  };
}

/**
 * Users worth considering tonight: anyone with an active goal or an open
 * follow-up. Scanning the whole user table every 30 seconds would be the
 * obvious way to make this expensive for no gain.
 */
export async function listNightWatchUserIds(
  app: FastifyInstance,
  limit: number,
): Promise<string[]> {
  const rows = await app.db
    .selectDistinct({ userId: sessionGoals.userId })
    .from(sessionGoals)
    .where(eq(sessionGoals.status, "active"))
    .limit(limit);

  const ids = new Set(rows.map((row) => row.userId));
  if (ids.size < limit) {
    const pending = await app.db
      .selectDistinct({ userId: proactiveTriggers.userId })
      .from(proactiveTriggers)
      .where(
        and(
          eq(proactiveTriggers.status, "pending"),
          eq(proactiveTriggers.kind, "follow_up"),
        ),
      )
      .limit(limit);
    for (const row of pending) {
      if (ids.size >= limit) break;
      ids.add(row.userId);
    }
  }
  return [...ids];
}

const NIGHT_WATCH_USER_SCAN_LIMIT = 200;

/**
 * One pass over the users worth considering.
 *
 * Two moments matter per user, both expressed in *their* timezone: the hour
 * the quiet window opens (plan and dispatch) and the digest hour (settle and
 * queue the single morning message). Everything in between is the desktop's
 * problem, not the scheduler's.
 */
export async function runNightWatchSweep(
  app: FastifyInstance,
  input: { now?: Date; userIds?: string[] } = {},
): Promise<NightWatchSweepResult> {
  const result = emptyNightWatchSweep();
  if (app.config?.ELYAN_NIGHT_WATCH_ENABLED !== true) {
    return result;
  }

  const now = input.now ?? new Date();
  const digestHour = app.config?.ELYAN_MORNING_DIGEST_HOUR ?? 8;
  const userIds =
    input.userIds ?? (await listNightWatchUserIds(app, NIGHT_WATCH_USER_SCAN_LIMIT));

  for (const userId of userIds) {
    result.usersConsidered += 1;
    try {
      const policy = await readProactivePolicy(app, userId);
      if (!policy.enabled) continue;

      const hour = localHourIn(now, policy.timezone);

      if (hour === policy.quietStartHour) {
        const planned = await planNightWatch(app, {
          userId,
          now,
          timezone: policy.timezone,
          quietStartHour: policy.quietStartHour,
          quietEndHour: policy.quietEndHour,
        });
        result.planned += planned.planned;
        result.dispatched += planned.dispatched;
      }

      if (hour === digestHour) {
        // The night that just ended is labelled by yesterday's date.
        const nightDate = nightDateKey(
          new Date(now.getTime() - 60 * 60_000),
          policy.timezone,
          policy.quietStartHour,
        );
        result.settled += await settleNightWatchJobs(app, {
          userId,
          nightDate,
          now,
        });
        const jobs = await listNightWatchJobs(app, { userId, nightDate });
        // Silence is the correct output when there was nothing to report.
        if (jobs.length === 0) continue;
        const sessionId = await resolveDigestSessionId(app, { userId, nightDate });
        const scheduled = await scheduleMorningDigest(app, {
          userId,
          nightDate,
          sessionId,
          due: now,
          now,
        });
        if (scheduled.status === "scheduled") {
          result.digestsScheduled += 1;
        }
      }
    } catch (error) {
      app.log?.warn?.({ error, userId }, "night watch sweep failed for user");
    }
  }

  return result;
}
