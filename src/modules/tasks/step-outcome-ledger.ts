import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";
import type { OutcomeAssessment } from "./outcome-verdict.js";
import { agentTrajectoryEpisodeId } from "./agent-trajectory.js";

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
  /** Adımın kendi ürettiği kanıt türleri (artifact / state_readback / …). */
  evidenceKinds?: string[];
};

/** Bir adımın arkasındaki kanıtın GÜCÜ. */
export type StepEvidenceStrength = "strong" | "weak" | "none";

const STRONG_EVIDENCE_KINDS = new Set(["artifact", "state_readback"]);
const WEAK_EVIDENCE_KINDS = new Set(["runtime_status", "tool_result"]);

/**
 * Ham `evidence` alanını KANIT TÜRÜNE çevirir.
 *
 * Runtime bu alanı iki şekilde gönderiyor: doğrulama kuralları tür adını
 * doğrudan yazıyor (`"artifact"`), yürütücü ise üretilen kanıtı sözlük olarak
 * gönderiyor (`{"path": "..."}`). İkisi de aynı kelimeye indirgenmeli.
 */
export function evidenceKindsFromValue(value: unknown): string[] {
  if (typeof value === "string") {
    const kind = value.trim().toLowerCase();
    return kind ? [kind] : [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => evidenceKindsFromValue(item)).slice(0, 8);
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const kinds: string[] = [];
    if (record.path !== undefined || record.artifact !== undefined) kinds.push("artifact");
    if (record.stateReadback !== undefined || record.state !== undefined) {
      kinds.push("state_readback");
    }
    if (typeof record.kind === "string") kinds.push(record.kind.trim().toLowerCase());
    if (kinds.length === 0) kinds.push("tool_result");
    return [...new Set(kinds)].slice(0, 8);
  }
  return [];
}

/**
 * ADIMIN KANIT GÜCÜ.
 *
 * Adımın kendi kanıtı yoksa GÖREV düzeyi doğrulama kanıtına düşülür: tek
 * adımlı derlenmiş görevlerde kanıt çoğu kez görev seviyesinde raporlanır.
 * İkisi de yoksa güç `none`'dır — ve `none`, "başarısız" demek değildir,
 * "bilmiyoruz" demektir. Bu ayrım skorlamada da korunur.
 */
export function stepEvidenceStrength(
  step: StepOutcomeRecord,
  taskEvidenceKinds: string[] = [],
): StepEvidenceStrength {
  if (step.verified === true) return "strong";
  const kinds = [
    ...(step.evidenceKinds ?? []),
    ...taskEvidenceKinds.map((kind) => String(kind ?? "").trim().toLowerCase()),
  ].filter(Boolean);
  if (kinds.some((kind) => STRONG_EVIDENCE_KINDS.has(kind))) return "strong";
  if (kinds.some((kind) => WEAK_EVIDENCE_KINDS.has(kind))) return "weak";
  return "none";
}

function eventSucceeded(event: Record<string, unknown>): boolean {
  if (typeof event.ok === "boolean") return event.ok;
  if (typeof event.errorCode === "string" && event.errorCode.trim()) return false;
  // Legacy desktop/Gemini events may omit `ok` and only carry their output.
  return event.output !== undefined || event.result !== undefined;
}

function safeTaskReasons(reasons: string[]): string[] {
  return reasons
    .map((reason) => {
      const normalized = String(reason ?? "").replace(/\s+/gu, " ").trim();
      if (!normalized) return null;
      if (/^error:/iu.test(normalized)) return "error_present";
      return /^[a-z0-9_.-]{2,100}$/iu.test(normalized)
        ? normalized
        : "reason_present";
    })
    .filter((reason): reason is string => Boolean(reason))
    .slice(0, 6);
}

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
        ok: eventSucceeded(event),
        ...(typeof event.errorCode === "string" && event.errorCode
          ? { errorCode: event.errorCode }
          : {}),
        ...(typeof event.verified === "boolean" ? { verified: event.verified } : {}),
        ...(() => {
          const kinds = evidenceKindsFromValue(event.evidence);
          return kinds.length > 0 ? { evidenceKinds: kinds } : {};
        })(),
        ...(typeof event.attempt === "number" ? { attempt: event.attempt } : {}),
        ...(typeof event.latencyMs === "number"
          ? { latencyMs: event.latencyMs }
          : typeof event.durationMs === "number"
            ? { latencyMs: event.durationMs }
            : {}),
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
  taskEvidenceKinds?: string[];
}): number {
  if (!input.step.ok) return 0;
  if (input.taskVerdict === "unfulfilled") return 0;
  // KANIT SKORU BELİRLER.
  //
  // Eskiden kanıtsız bir başarı TAM kredi alıyordu (`verified` alanı yoksa
  // 100). Yani "runtime bitti" ile "istenen şey gerçekten oldu" öğrenmede
  // aynı ağırlıktaydı; doğrulanmamış işler araç sıralamasını yukarı çekiyordu.
  // Artık kanıt gücü krediyi belirler ve kanıtsız çağrı hiç kredi almaz —
  // ama aşağıdaki `evidenceBacked` bayrağı sayesinde tahminciye BAŞARISIZLIK
  // olarak da girmez, sadece sayılmaz.
  const strength = stepEvidenceStrength(input.step, input.taskEvidenceKinds ?? []);
  if (strength === "none") return 0;
  if (input.taskVerdict === "degraded") return strength === "strong" ? 50 : 25;
  return strength === "strong" ? 100 : 50;
}

/**
 * Görev sonucundaki doğrulama kanıtı türleri.
 *
 * `verification.checks[].evidence` yalnız GEÇMİŞ kontrollerden okunur:
 * başarısız bir kontrol kanıt değildir.
 */
export function taskVerificationEvidenceKinds(result: unknown): string[] {
  const record = (result ?? {}) as Record<string, unknown>;
  const verification = record.verification;
  if (!verification || typeof verification !== "object") return [];
  const checks = (verification as Record<string, unknown>).checks;
  if (!Array.isArray(checks)) return [];
  const kinds = checks.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const check = value as Record<string, unknown>;
    if (check.passed !== true) return [];
    return evidenceKindsFromValue(check.evidence);
  });
  return [...new Set(kinds)].slice(0, 8);
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
    episodeId?: string;
  },
): Promise<number> {
  const steps = extractStepOutcomes(input.result);
  if (steps.length === 0) return 0;
  // Görev düzeyi doğrulama kanıtı: tek adımlı derlenmiş görevlerde kanıt
  // çoğu kez adımda değil görev sonucunda raporlanır.
  const taskEvidenceKinds = taskVerificationEvidenceKinds(input.result);
  // learning_events'in görev anahtarı araç başına tek satırdır. Aynı araç
  // retry/replan döngüsünde birden fazla çalışmışsa çağrıları tek satırda
  // topluyoruz; ayrıntılı sıra/attempt bilgisi metadata.calls içinde kalır,
  // gerçek episode ise bütün tool olaylarını ayrıca saklar.
  const grouped = new Map<string, Array<{ step: StepOutcomeRecord; sequence: number }>>();
  steps.forEach((step, sequence) => {
    const calls = grouped.get(step.tool) ?? [];
    calls.push({ step, sequence });
    grouped.set(step.tool, calls);
  });
  const aggregated = [...grouped.entries()].map(([tool, calls]) => {
    const last = calls[calls.length - 1]?.step ?? { tool, ok: false };
    const verified = calls.some((call) => call.step.verified === true)
      ? true
      : calls.every((call) => call.step.verified === false)
        ? false
        : last.verified;
    const evidenceKinds = [
      ...new Set(calls.flatMap((call) => call.step.evidenceKinds ?? [])),
    ].slice(0, 8);
    return {
      step: {
        ...last,
        tool,
        ok: calls.some((call) => call.step.ok),
        ...(typeof verified === "boolean" ? { verified } : {}),
        ...(evidenceKinds.length > 0 ? { evidenceKinds } : {}),
        ...(calls.some((call) => typeof call.step.attempt === "number")
          ? {
              attempt: Math.max(
                ...calls.map((call) => call.step.attempt ?? 1),
              ),
            }
          : {}),
      },
      firstSequence: calls[0]?.sequence ?? 0,
      calls,
    };
  });
  try {
    const insertedRows = await app.db.insert(learningEvents).values(
      aggregated.map(({ step, firstSequence, calls }) => ({
        userId: input.userId,
        taskId: input.taskId,
        type: "tool_outcome",
        key: step.tool,
        value: step.ok ? "ok" : "error",
        confidence: scoreStepOutcome({
          step,
          taskVerdict: input.assessment.verdict,
          taskEvidenceKinds,
        }),
        scope: "user" as const,
        source: "interaction" as const,
        privacyLevel: "safe" as const,
        metadata: {
          contract: "elyan.tool_outcome.v1",
          sequence: firstSequence,
          callCount: calls.length,
          hadRetryOrReplan: calls.length > 1,
          calls: calls.map(({ step: call, sequence }) => ({
            sequence,
            ok: call.ok,
            ...(typeof call.verified === "boolean" ? { verified: call.verified } : {}),
            ...(typeof call.attempt === "number" ? { attempt: call.attempt } : {}),
            ...(typeof call.latencyMs === "number" ? { latencyMs: call.latencyMs } : {}),
            ...(call.errorCode ? { errorCode: call.errorCode } : {}),
          })),
          route: input.route,
          device: input.device,
          intentKind: input.intentKind,
          taskVerdict: input.assessment.verdict,
          // TAHMİNCİNİN KAPISI. `false` olan satır `estimateToolSuccess`
          // tarafından hiç sayılmaz: doğrulanmamış bir çağrı ne başarı ne
          // başarısızlık kanıtıdır. Alanın hiç olmadığı ESKİ satırlar
          // bilinçli olarak sayılmaya devam eder — bugünkü sinyali yok
          // etmemek için; 90 günlük pencere onları kendiliğinden düşürür.
          evidenceBacked: stepEvidenceStrength(step, taskEvidenceKinds) !== "none",
          evidenceStrength: stepEvidenceStrength(step, taskEvidenceKinds),
          ...(step.evidenceKinds && step.evidenceKinds.length > 0
            ? { evidenceKinds: step.evidenceKinds }
            : {}),
          ...(input.assessment.reasons.length > 0
            ? { taskReasons: safeTaskReasons(input.assessment.reasons) }
            : {}),
          ...(step.errorCode ? { errorCode: step.errorCode } : {}),
          ...(typeof step.verified === "boolean" ? { verified: step.verified } : {}),
          ...(typeof step.attempt === "number" ? { attempt: step.attempt } : {}),
          ...(typeof step.latencyMs === "number" ? { stepLatencyMs: step.latencyMs } : {}),
          episodeId: input.episodeId ?? agentTrajectoryEpisodeId(input.taskId),
          ...(typeof input.latencyMs === "number" ? { latencyMs: input.latencyMs } : {}),
        },
      })),
    ).onConflictDoNothing().returning({ id: learningEvents.id });
    return insertedRows.length;
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "step outcomes not recorded",
    );
    return 0;
  }
}
