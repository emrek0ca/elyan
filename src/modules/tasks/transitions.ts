import type { TaskStatus } from "../../contracts/domain.js";
import { conflict } from "../../lib/errors.js";

const allowedTransitions: Record<TaskStatus, TaskStatus[]> = {
  queued: ["planning", "running", "canceled"],
  planning: ["running", "waiting_approval", "completed", "failed", "canceled"],
  running: ["planning", "waiting_approval", "completed", "failed", "canceled"],
  waiting_approval: ["planning", "running", "completed", "failed", "canceled"],
  completed: [],
  failed: [],
  canceled: [],
};

export function assertTaskTransition(currentStatus: TaskStatus, nextStatus: TaskStatus): void {
  if (currentStatus === nextStatus) {
    return;
  }

  if (!allowedTransitions[currentStatus].includes(nextStatus)) {
    throw conflict(`Task cannot move from ${currentStatus} to ${nextStatus}`);
  }
}

export function isTerminalTaskStatus(status: TaskStatus): boolean {
  return ["completed", "failed", "canceled"].includes(status);
}
