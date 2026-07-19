import type { TaskStatus } from "../../contracts/domain.js";
import { conflict } from "../../lib/errors.js";

const allowedTransitions: Record<TaskStatus, TaskStatus[]> = {
  // queued -> completed/failed: bir görev lease/stale süpürücüsüyle queue'ya
  // geri atıldıktan sonra, masaüstü runtime yürütmeyi kendi thread'inde
  // bitirip geç ama DÜRÜST bir terminal rapor gönderebilir. Bu geçiş kapalıyken
  // rapor 409 alıyor ve sonuç kalıcı kayboluyordu; runtime'ın gerçek sonucu
  // kazanır (ensureTaskRuntimeOwnership dönen runtime'ın görevi yeniden
  // sahiplenmesine zaten izin verir).
  queued: ["planning", "running", "completed", "failed", "canceled"],
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
