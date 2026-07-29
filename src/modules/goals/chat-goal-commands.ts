import type { FastifyInstance } from "fastify";
import { advanceGoal, createGoal, getActiveGoalForContext } from "./service.js";

type TurnGoalOp = {
  op: "advance" | "complete" | "block" | "open";
  goalId?: string;
  step?: string;
  next?: string;
};

/**
 * Turn envelope'daki goal_ops'u goals servisine kalıcılaştırır. Envelope'daki
 * goalId model üretimi olduğu için güvenilmez — "open" dışındaki op'lar aktif
 * hedefe uygulanır; goalId ancak kullanıcının kendi hedefiyle eşleşirse
 * kullanılır (cross-user yazım imkânsız: tüm servis çağrıları userId scope'lu).
 */
export async function applyTurnGoalOps(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId?: string | null;
    sessionId?: string | null;
    goalOps: TurnGoalOp[];
    userMessage: string;
  },
): Promise<void> {
  // Tur başına en fazla 1 open + 3 ilerleme — model taşkını DB'ye yansımasın.
  let opened = 0;
  let advancedCount = 0;
  for (const op of input.goalOps.slice(0, 8)) {
    try {
      if (op.op === "open") {
        if (opened >= 1) continue;
        opened += 1;
        await createGoal(app, {
          userId: input.userId,
          sessionId: input.sessionId ?? undefined,
          taskId: input.taskId ?? undefined,
          title: (op.step ?? op.next ?? input.userMessage).slice(0, 200),
        });
        continue;
      }
      if (advancedCount >= 3) continue;
      const active = await getActiveGoalForContext(app, {
        userId: input.userId,
        sessionId: input.sessionId ?? null,
      });
      const goalId =
        op.goalId && op.goalId === active?.id ? op.goalId : active?.id;
      if (!goalId || !active) continue;
      advancedCount += 1;
      if (op.op === "complete") {
        await advanceGoal(app, {
          userId: input.userId,
          goalId,
          step: active.maxSteps,
          ofSteps: active.maxSteps,
          advancedTo: op.step ?? op.next ?? "Hedef tamamlandı",
          done: true,
        });
      } else {
        await advanceGoal(app, {
          userId: input.userId,
          goalId,
          step: Math.min(active.currentStep + 1, active.maxSteps),
          ofSteps: active.maxSteps,
          advancedTo: op.step ?? op.next ?? "İlerleme kaydedildi",
          blocker: op.op === "block" ? op.next ?? op.step ?? "Engel bildirildi" : null,
          done: false,
        });
      }
    } catch {
      // Tek op hatası kalanları durdurmaz; sohbet cevabı hiç etkilenmez.
    }
  }
}
