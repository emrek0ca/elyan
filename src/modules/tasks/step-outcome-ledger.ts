import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import type { OutcomeAssessment } from "./outcome-verdict.js";

/**
 * ADIM DÜZEYİ DENEYİM DEFTERİ — öğrenmenin ham maddesi.
 *
 * NEDEN VAR
 * ---------
 * Bugün deneyim yalnız GÖREV düzeyinde kayıtlı (epizodik hafıza, Katman 1).
 * Ama "hangi aracı ne zaman kullanmalı" sorusunun cevabı görevde değil ADIMDA:
 *   P(success | task, tool, context)
 * Bu olasılığı hesaplayacak hiçbir veri yoktu.
 *
 * ÖLÇÜLDÜ (2026-08-22):
 *   agent_steps    → 0 satır  (şema doğru, motoru kapalı)
 *   operator_steps → 0 satır
 *   learning_events→ 45.676 satır ama araç düzeyi sonuç YOK
 *     (routing 15.503 · bridge 10.456 · workflow 8.560 · correction 3.806)
 *
 * Yani araç seçimini öğrenebilecek tek veri kaynağı hiç doldurulmamış.
 * Küçük yardımcı modeller, self-model ve prosedürel hafıza — hepsi bu
 * deftere bağlı. Önce defter.
 *
 * NE KAYDEDER (kullanıcının tarif ettiği zincir):
 *   intent → plan → tool → result → hata → başarı skoru
 *
 * NE KAYDETMEZ: kullanıcı içeriği. Anahtar ve değer araç/sonuç düzeyindedir;
 * isteğin kendisi epizodik hafızada (kullanıcı kapsamlı) durur.
 */

export type StepOutcomeRecord = {
  tool: string;
  ok: boolean;
  errorCode?: string;
  verified?: boolean;
  attempt?: number;
  latencyMs?: number;
};

/** Görev sonucundan araç düzeyi olayları çıkar. */
export function extractStepOutcomes(result: unknown): StepOutcomeRecord[] {
  const record = (result ?? {}) as Record<string, unknown>;
  const events = Array.isArray(record.toolEvents)
    ? (record.toolEvents as Array<Record<string, unknown>>)
    : [];
  return events.flatMap((event): StepOutcomeRecord[] => {
    const tool = String(event.tool ?? "").trim();
    if (!tool) return [];
    return [
      {
        tool,
        ok: event.ok === true,
        ...(typeof event.errorCode === "string" && event.errorCode
          ? { errorCode: event.errorCode }
          : {}),
        ...(typeof event.verified === "boolean" ? { verified: event.verified } : {}),
        ...(typeof event.attempt === "number" ? { attempt: event.attempt } : {}),
      },
    ];
  });
}

/**
 * Başarı skoru — araç düzeyinde tek sayı.
 *
 * Araç "ok" dese bile GÖREV kullanıcı açısından başarısızsa skor düşer:
 * `document_write` dosyayı yazdı ama içine konu tarifi yazıldıysa o araç
 * çağrısı başarılı SAYILMAZ. Bu ayrım olmadan model yanlış şeyi öğrenir.
 */
export function scoreStepOutcome(input: {
  step: StepOutcomeRecord;
  taskVerdict: OutcomeAssessment["verdict"];
}): number {
  if (!input.step.ok) return 0;
  if (input.taskVerdict === "unfulfilled") return 0;
  if (input.taskVerdict === "degraded") return 50;
  return input.step.verified === false ? 75 : 100;
}

/**
 * Adım sonuçlarını deftere yaz.
 *
 * FAIL-OPEN: yazamazsa görev akışı etkilenmez.
 */
export async function recordStepOutcomes(
  app: FastifyInstance,
  input: {
    userId: string;
    taskId: string;
    route: string;
    device: string;
    intentKind: string;
    assessment: OutcomeAssessment;
    result: unknown;
    latencyMs?: number;
  },
): Promise<number> {
  const steps = extractStepOutcomes(input.result);
  if (steps.length === 0) return 0;
  try {
    await app.db.insert(learningEvents).values(
      steps.map((step, index) => ({
        userId: input.userId,
        taskId: input.taskId,
        type: "tool_outcome",
        key: step.tool,
        value: step.ok ? "ok" : "error",
        confidence: scoreStepOutcome({ step, taskVerdict: input.assessment.verdict }),
        scope: "user" as const,
        source: "interaction" as const,
        privacyLevel: "safe" as const,
        metadata: {
          contract: "elyan.tool_outcome.v1",
          sequence: index,
          route: input.route,
          device: input.device,
          intentKind: input.intentKind,
          taskVerdict: input.assessment.verdict,
          ...(input.assessment.reasons.length > 0
            ? { taskReasons: input.assessment.reasons.slice(0, 6) }
            : {}),
          ...(step.errorCode ? { errorCode: step.errorCode } : {}),
          ...(typeof step.verified === "boolean" ? { verified: step.verified } : {}),
          ...(typeof step.attempt === "number" ? { attempt: step.attempt } : {}),
          ...(typeof input.latencyMs === "number" ? { latencyMs: input.latencyMs } : {}),
        },
      })),
    );
    return steps.length;
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "step outcomes not recorded",
    );
    return 0;
  }
}
