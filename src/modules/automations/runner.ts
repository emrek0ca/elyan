import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { createTask } from "../tasks/service.js";
import {
  claimDueAutomation,
  markAutomationDispatchFailed,
  markAutomationDispatched,
  type TaskAutomationRow,
} from "./service.js";

export type AutomationSweepResult = {
  processed: number;
  dispatched: number;
  failed: number;
};

function safeErrorCode(error: unknown): string {
  if (error && typeof error === "object" && "code" in error) {
    const code = String((error as { code?: unknown }).code ?? "").trim();
    if (code) return code.slice(0, 120);
  }
  return "automation_dispatch_failed";
}

function capabilities(row: TaskAutomationRow): string[] {
  return Array.isArray(row.requestedCapabilities)
    ? [...new Set(row.requestedCapabilities.map((value) => String(value ?? "").trim()).filter(Boolean))].slice(0, 20)
    : [];
}

async function dispatchAutomation(
  app: FastifyInstance,
  row: TaskAutomationRow,
  now: Date,
): Promise<void> {
  const scheduledAt = row.nextRunAt;
  const runKey = `automation:${row.id}:${scheduledAt.toISOString()}`;
  const result = await createTask(app, {
    userId: row.userId,
    targetDeviceId: row.targetDeviceId ?? undefined,
    requestedTargetDeviceId: row.targetDeviceId ?? undefined,
    title: row.title,
    payload: {
      prompt: row.prompt,
      source: "mobile",
      metadata: {
        automationId: row.id,
        automationRun: true,
        sourceTaskId: row.sourceTaskId,
        scheduledAt: scheduledAt.toISOString(),
      },
    },
    requestedCapabilities: capabilities(row),
    requestedCapabilitiesResolved: true,
    requestId: randomUUID(),
    idempotencyKey: runKey,
  });
  await markAutomationDispatched(app, {
    automationId: row.id,
    taskId: result.task.id,
    scheduledAt,
    intervalMinutes: row.intervalMinutes,
    now,
  });
}

export async function processDueAutomations(
  app: FastifyInstance,
  input: { limit?: number; now?: Date } = {},
): Promise<AutomationSweepResult> {
  const limit = Math.max(1, Math.min(input.limit ?? 5, 20));
  const now = input.now ?? new Date();
  const result: AutomationSweepResult = { processed: 0, dispatched: 0, failed: 0 };
  for (let index = 0; index < limit; index += 1) {
    const row = await claimDueAutomation(app, { now });
    if (!row) break;
    result.processed += 1;
    try {
      await dispatchAutomation(app, row, now);
      result.dispatched += 1;
    } catch (error) {
      result.failed += 1;
      await markAutomationDispatchFailed(app, {
        automationId: row.id,
        failureCount: row.failureCount,
        intervalMinutes: row.intervalMinutes,
        errorCode: safeErrorCode(error),
        now,
      }).catch(() => undefined);
      app.log.warn?.(
        { automationId: row.id, errorCode: safeErrorCode(error) },
        "automation dispatch failed",
      );
    }
  }
  return result;
}
