import { randomUUID } from "node:crypto";

export const taskExecutionEventTypes = [
  "task.accepted",
  "plan.ready",
  "step.started",
  "tool.called",
  "tool.result",
  "approval.required",
  "step.verified",
  "task.completed",
  "task.failed",
] as const;

export type TaskExecutionEventType = (typeof taskExecutionEventTypes)[number];

export type TaskExecutionEvent = {
  eventId: string;
  type: TaskExecutionEventType;
  taskId: string;
  turnId: string | null;
  planRevision: number;
  stepId: string;
  attempt: number;
  occurredAt: string;
  payload: Record<string, unknown>;
  evidenceRefs: string[];
};

export function buildTaskExecutionEvent(input: {
  type: TaskExecutionEventType;
  taskId: string;
  turnId?: string | null;
  planRevision?: number;
  stepId?: string | null;
  attempt?: number;
  payload?: Record<string, unknown>;
  evidenceRefs?: string[];
  eventId?: string;
  occurredAt?: string;
}): TaskExecutionEvent {
  return {
    eventId: input.eventId ?? randomUUID(),
    type: input.type,
    taskId: input.taskId,
    turnId: input.turnId ?? null,
    planRevision: Math.max(1, Math.floor(input.planRevision ?? 1)),
    stepId: input.stepId ?? "",
    attempt: Math.max(1, Math.floor(input.attempt ?? 1)),
    occurredAt: input.occurredAt ?? new Date().toISOString(),
    payload: input.payload ?? {},
    evidenceRefs: [...new Set((input.evidenceRefs ?? []).filter(Boolean))].slice(0, 16),
  };
}
