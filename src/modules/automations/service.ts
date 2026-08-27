import { and, asc, desc, eq, lte, or } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { devices, taskAutomations, tasks } from "../../db/schema.js";
import { conflict, badRequest, notFound } from "../../lib/errors.js";
import { assessTaskOutcome } from "../tasks/outcome-verdict.js";
import { asRecord as readRecord } from "../../lib/record.js";

export type TaskAutomationRow = typeof taskAutomations.$inferSelect;

const AUTOMATION_INTERVAL_MS = new Set([
  15 * 60_000,
  60 * 60_000,
  6 * 60 * 60_000,
  12 * 60 * 60_000,
  24 * 60 * 60_000,
  7 * 24 * 60 * 60_000,
]);

/**
 * Repetition is fail-closed: a capability must be explicitly known to be a
 * read-only observation before it can run without a fresh user approval.
 * Keep this list local instead of importing the night-watch module because
 * that module creates tasks and would introduce a service import cycle.
 */
const AUTOMATION_ALLOWED_CAPABILITIES = new Set([
  "calendar.list_events",
  "data_analyze",
  "desktop_os.status",
  "directory_tree",
  "document_read",
  "file_find",
  "file_read",
  "file_search",
  "get_calendar_events",
  "get_reminders",
  "get_weather",
  "git_diff",
  "git_status",
  "image_read",
  "math_solve",
  "ocr_read",
  "retrieve_context",
  "sys_info",
  "system.capabilities",
  "text_analyze",
  "web.fetch_url",
  "web.numeric_facts",
  "web.research",
  "web.search",
  "web_research",
]);

function compactText(value: unknown, max: number): string {
  const text = String(value ?? "").replace(/\s+/g, " ").trim();
  return text.length <= max ? text : `${text.slice(0, max - 1).trimEnd()}…`;
}

function readPrompt(payload: unknown): string {
  const prompt = readRecord(payload)?.prompt;
  return typeof prompt === "string" ? compactText(prompt, 20_000) : "";
}

function readCapabilities(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.map((item) => String(item ?? "").trim()).filter(Boolean))].slice(0, 20)
    : [];
}

function readExpectedOutputs(payload: unknown): unknown[] {
  const record = readRecord(payload);
  const metadata = readRecord(record?.metadata);
  const workOrder = readRecord(metadata?.desktopWorkOrder) ?? readRecord(record?.desktopWorkOrder);
  const expected = workOrder?.expectedOutputs ?? metadata?.expectedOutputs ?? record?.expectedOutputs;
  return Array.isArray(expected) ? expected : [];
}

function readRouteDecision(payload: unknown): Record<string, unknown> {
  const record = readRecord(payload);
  const metadata = readRecord(record?.metadata);
  return readRecord(metadata?.routeDecision) ?? readRecord(record?.routeDecision) ?? {};
}

function readCapabilitySequence(payload: unknown): string[] {
  const record = readRecord(payload);
  const metadata = readRecord(record?.metadata);
  const workOrder = readRecord(metadata?.desktopWorkOrder) ?? readRecord(record?.desktopWorkOrder);
  const preview = readRecord(workOrder?.planPreview);
  const steps = Array.isArray(preview?.steps) ? preview.steps : [];
  return readCapabilities(steps.flatMap((step) => {
    const capability = readRecord(step)?.capability;
    return typeof capability === "string" ? [capability] : [];
  }));
}

export function isAutomationCapabilitySafe(capability: string): boolean {
  const normalized = capability.trim().toLowerCase();
  return normalized.length > 0 && AUTOMATION_ALLOWED_CAPABILITIES.has(normalized);
}

export function nextAutomationRunAt(input: {
  scheduledAt: Date;
  now: Date;
  intervalMinutes: number;
}): Date {
  const intervalMs = input.intervalMinutes * 60_000;
  if (!AUTOMATION_INTERVAL_MS.has(intervalMs)) {
    throw badRequest("Otomasyon aralığı desteklenmiyor.");
  }
  let next = new Date(input.scheduledAt.getTime() + intervalMs);
  while (next.getTime() <= input.now.getTime()) {
    next = new Date(next.getTime() + intervalMs);
  }
  return next;
}

/** A fast child task may settle before its dispatch row is annotated. */
export function canSettleAutomationTask(input: {
  lastTaskId: string | null;
  taskId: string;
}): boolean {
  return input.lastTaskId == null || input.lastTaskId === input.taskId;
}

function assertTimezone(timezone: string): string {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: timezone }).format();
  } catch {
    throw badRequest("Geçerli bir saat dilimi gerekli.");
  }
  return timezone;
}

function assertAutomationIntervalMinutes(intervalMinutes: number): void {
  if (!AUTOMATION_INTERVAL_MS.has(intervalMinutes * 60_000)) {
    throw badRequest("Otomasyon aralığı desteklenmiyor.");
  }
}

function shapeAutomation(row: TaskAutomationRow) {
  return {
    id: row.id,
    sourceTaskId: row.sourceTaskId,
    targetDeviceId: row.targetDeviceId,
    title: row.title,
    prompt: row.prompt,
    requestedCapabilities: readCapabilities(row.requestedCapabilities),
    intervalMinutes: row.intervalMinutes,
    timezone: row.timezone,
    status: row.status,
    nextRunAt: row.nextRunAt.toISOString(),
    lastRunAt: row.lastRunAt?.toISOString() ?? null,
    lastTaskId: row.lastTaskId,
    lastOutcome: row.lastOutcome,
    lastError: row.lastError,
    failureCount: row.failureCount,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

export async function createAutomation(
  app: FastifyInstance,
  input: {
    userId: string;
    sourceTaskId: string;
    title?: string;
    intervalMinutes: number;
    timezone: string;
    firstRunAt?: Date;
    targetDeviceId?: string;
  },
) {
  assertAutomationIntervalMinutes(input.intervalMinutes);
  const sourceRows = await app.db
    .select()
    .from(tasks)
    .where(and(eq(tasks.id, input.sourceTaskId), eq(tasks.userId, input.userId)))
    .limit(1);
  const sourceTask = sourceRows[0];
  if (!sourceTask) throw notFound("Kaynak görev bulunamadı.");
  if (sourceTask.status !== "completed") {
    throw conflict("Yalnız doğrulanmış olarak tamamlanan görev otomasyona çevrilebilir.");
  }

  const sourcePayload = readRecord(sourceTask.payload) ?? {};
  const prompt = readPrompt(sourcePayload);
  if (!prompt) throw conflict("Kaynak görevde tekrarlanabilir bir istek yok.");
  const assessment = assessTaskOutcome({
    status: sourceTask.status,
    request: prompt,
    expectedOutputs: readExpectedOutputs(sourcePayload),
    result: sourceTask.result,
    assistantText: sourceTask.summary,
    error: sourceTask.error,
  });
  if (assessment.verdict !== "fulfilled") {
    throw conflict("Kaynak görevin sonucu doğrulanmadı; otomasyon kaydedilmedi.", {
      verdict: assessment.verdict,
      reasons: assessment.reasons.slice(0, 4),
    });
  }

  const capabilities = readCapabilities(sourceTask.requestedCapabilities);
  const planCapabilities = readCapabilitySequence(sourcePayload);
  const allCapabilities = [...new Set([...capabilities, ...planCapabilities])];
  if (allCapabilities.length === 0 || allCapabilities.some((capability) => !isAutomationCapabilitySafe(capability))) {
    throw conflict("Bu görev güvenli bir otomasyon kapsamına girmiyor.");
  }
  const routeDecision = readRouteDecision(sourcePayload);
  if (routeDecision.requiresApproval === true || routeDecision.privacyClass === "side_effect") {
    throw conflict("Onay gerektiren görevler otomasyona sessizce bağlanamaz.");
  }

  const timezone = assertTimezone(input.timezone);
  const now = new Date();
  const firstRunAt = input.firstRunAt ?? new Date(now.getTime() + input.intervalMinutes * 60_000);
  if (firstRunAt.getTime() < now.getTime() - 30_000) {
    throw badRequest("İlk çalışma zamanı geçmiş olamaz.");
  }

  if (input.targetDeviceId) {
    const targetRows = await app.db
      .select({ id: devices.id })
      .from(devices)
      .where(and(eq(devices.id, input.targetDeviceId), eq(devices.userId, input.userId)))
      .limit(1);
    if (!targetRows[0]) throw notFound("Otomasyon cihazı bulunamadı.");
  }

  const rows = await app.db
    .insert(taskAutomations)
    .values({
      userId: input.userId,
      sourceTaskId: sourceTask.id,
      targetDeviceId: input.targetDeviceId ?? sourceTask.targetDeviceId,
      title: compactText(input.title || sourceTask.title || "Otomasyon", 200),
      prompt,
      requestedCapabilities: allCapabilities,
      intervalMinutes: input.intervalMinutes,
      timezone,
      status: "active",
      nextRunAt: firstRunAt,
      updatedAt: now,
    })
    .returning();
  const created = rows[0];
  if (!created) throw conflict("Otomasyon kaydedilemedi.");
  return shapeAutomation(created);
}

export async function listAutomations(
  app: FastifyInstance,
  input: { userId: string; limit: number },
) {
  const rows = await app.db
    .select()
    .from(taskAutomations)
    .where(eq(taskAutomations.userId, input.userId))
    .orderBy(desc(taskAutomations.createdAt))
    .limit(input.limit);
  return { automations: rows.map(shapeAutomation) };
}

export async function updateAutomation(
  app: FastifyInstance,
  input: { userId: string; automationId: string; status: "active" | "paused" },
) {
  const rows = await app.db
    .select()
    .from(taskAutomations)
    .where(and(eq(taskAutomations.id, input.automationId), eq(taskAutomations.userId, input.userId)))
    .limit(1);
  const current = rows[0];
  if (!current || current.status === "canceled") throw notFound("Otomasyon bulunamadı.");
  const now = new Date();
  const nextRunAt = input.status === "active"
    ? new Date(now.getTime() + current.intervalMinutes * 60_000)
    : current.nextRunAt;
  const updated = await app.db
    .update(taskAutomations)
    .set({ status: input.status, nextRunAt, leaseUntil: null, updatedAt: now })
    .where(and(eq(taskAutomations.id, current.id), eq(taskAutomations.userId, input.userId)))
    .returning();
  if (!updated[0]) throw notFound("Otomasyon bulunamadı.");
  return shapeAutomation(updated[0]);
}

export async function cancelAutomation(
  app: FastifyInstance,
  input: { userId: string; automationId: string },
) {
  const now = new Date();
  const rows = await app.db
    .update(taskAutomations)
    .set({ status: "canceled", leaseUntil: null, updatedAt: now })
    .where(and(eq(taskAutomations.id, input.automationId), eq(taskAutomations.userId, input.userId)))
    .returning();
  if (!rows[0]) throw notFound("Otomasyon bulunamadı.");
  return { ok: true, automation: shapeAutomation(rows[0]) };
}

export async function claimDueAutomation(
  app: FastifyInstance,
  input: { now?: Date } = {},
): Promise<TaskAutomationRow | null> {
  const now = input.now ?? new Date();
  return app.db.transaction(async (tx) => {
    const rows = await tx
      .select()
      .from(taskAutomations)
      .where(and(
        or(
          and(eq(taskAutomations.status, "active"), lte(taskAutomations.nextRunAt, now)),
          and(eq(taskAutomations.status, "running"), lte(taskAutomations.leaseUntil, now)),
        ),
      ))
      .orderBy(asc(taskAutomations.nextRunAt))
      .limit(1)
      .for("update", { skipLocked: true });
    const candidate = rows[0];
    if (!candidate) return null;
    const claimed = await tx
      .update(taskAutomations)
      .set({ status: "running", leaseUntil: new Date(now.getTime() + 10 * 60_000), updatedAt: now })
      .where(eq(taskAutomations.id, candidate.id))
      .returning();
    return claimed[0] ?? null;
  });
}

export async function markAutomationDispatched(
  app: FastifyInstance,
  input: { automationId: string; taskId: string; scheduledAt: Date; now?: Date; intervalMinutes: number },
) {
  const now = input.now ?? new Date();
  const nextRunAt = nextAutomationRunAt({
    scheduledAt: input.scheduledAt,
    now,
    intervalMinutes: input.intervalMinutes,
  });
  const currentRows = await app.db
    .select({
      status: taskAutomations.status,
      lastOutcome: taskAutomations.lastOutcome,
      lastError: taskAutomations.lastError,
      nextRunAt: taskAutomations.nextRunAt,
    })
    .from(taskAutomations)
    .where(eq(taskAutomations.id, input.automationId))
    .limit(1);
  const current = currentRows[0];
  if (!current || current.status === "canceled") return;
  const alreadySettled =
    current.lastOutcome != null && current.lastOutcome !== "dispatched";
  await app.db
    .update(taskAutomations)
    .set({
      status: current.status === "running" ? "active" : current.status,
      nextRunAt: current.status === "running" ? nextRunAt : current.nextRunAt,
      lastRunAt: now,
      lastTaskId: input.taskId,
      lastOutcome: alreadySettled ? current.lastOutcome : "dispatched",
      lastError: alreadySettled ? current.lastError : null,
      failureCount: 0,
      leaseUntil: null,
      updatedAt: now,
    })
    .where(eq(taskAutomations.id, input.automationId));
}

export async function markAutomationDispatchFailed(
  app: FastifyInstance,
  input: { automationId: string; failureCount: number; intervalMinutes: number; errorCode?: string; now?: Date },
) {
  const now = input.now ?? new Date();
  const failureCount = input.failureCount + 1;
  const paused = failureCount >= 3;
  await app.db
    .update(taskAutomations)
    .set({
      status: paused ? "paused" : "active",
      nextRunAt: new Date(now.getTime() + Math.max(5, Math.min(input.intervalMinutes, 15)) * 60_000),
      lastRunAt: now,
      lastOutcome: "dispatch_failed",
      lastError: compactText(input.errorCode || "dispatch_failed", 240),
      failureCount,
      leaseUntil: null,
      updatedAt: now,
    })
    .where(and(eq(taskAutomations.id, input.automationId), eq(taskAutomations.status, "running")));
}

export async function settleAutomationTask(
  app: FastifyInstance,
  input: {
    userId: string;
    task: { id: string; status: string; payload: unknown; result?: unknown; summary?: string | null; error?: string | null };
  },
) {
  const payload = readRecord(input.task.payload);
  const metadata = readRecord(payload?.metadata);
  const automationId = typeof metadata?.automationId === "string" ? metadata.automationId : "";
  if (!automationId) return;
  const rows = await app.db
    .select()
    .from(taskAutomations)
    .where(and(
      eq(taskAutomations.id, automationId),
      eq(taskAutomations.userId, input.userId),
    ))
    .limit(1);
  const automation = rows[0];
  if (!automation || !canSettleAutomationTask({
    lastTaskId: automation.lastTaskId,
    taskId: input.task.id,
  })) return;
  const assessment = assessTaskOutcome({
    status: input.task.status,
    request: readPrompt(payload),
    expectedOutputs: readExpectedOutputs(payload),
    result: input.task.result,
    assistantText: input.task.summary,
    error: input.task.error,
  });
  const paused = assessment.verdict !== "fulfilled";
  await app.db
    .update(taskAutomations)
    .set({
      status: paused ? "paused" : "active",
      lastOutcome: assessment.verdict,
      lastError: assessment.reasons[0] ?? null,
      leaseUntil: null,
      updatedAt: new Date(),
    })
    .where(eq(taskAutomations.id, automation.id));
}
