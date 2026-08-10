/**
 * Ajan döngüsünün ölçümü ve kredi ataması.
 *
 * NEDEN
 * -----
 * Döngü hakkında bugün yalnız "geçti/kaldı" biliniyor. Bir görevin 2 adımda
 * mı 14 adımda mı bittiği, kaç kez yeniden denendiği, bütçe tükendiği için
 * mi yoksa hedefe ulaştığı için mi durduğu hiçbir yerde toplanmıyor. Bu
 * bilinmeden "döngüyü iyileştirdik" cümlesi ölçülemez bir iddiadır.
 *
 * İyi haber: veri ZATEN geliyor. Masaüstü runtime her adım için
 * `attemptCount`, `verificationStatus`, `durationMs`, `startedAt/completedAt`
 * bildiriyor (elyan.task_trace sözleşmesi). Eksik olan toplama.
 *
 * KREDİ ATAMASI
 * -------------
 * Mevcut başarısızlık imzası "hangi ARAÇ patladı"yı söylüyor. Asıl soru
 * çoğu zaman bu değil: "Chrome u kapat" vakasında hiçbir araç patlamadı —
 * suçlu, o adımı plana koyan KARARdı. Bu yüzden burada patlayan adımın
 * yanında onu plana kimin koyduğu da işaretleniyor: router'ın yetenek ipucu
 * mu, yoksa planlayıcının kendi seçimi mi.
 *
 * Saf fonksiyonlar — DB/ağ yok, kolay test edilir.
 */

export type LoopTerminationReason =
  | "goal_reached"
  | "budget_exhausted"
  | "step_failure"
  | "no_plan"
  | "unknown";

export type LoopStepReport = {
  id?: unknown;
  status?: unknown;
  capability?: unknown;
  tool?: unknown;
  verificationStatus?: unknown;
  attemptCount?: unknown;
  durationMs?: unknown;
};

export type LoopMetrics = {
  /** Planda kaç adım vardı. */
  plannedStepCount: number;
  /** Kaçı gerçekten çalıştı (pending/skipped olmayan). */
  executedStepCount: number;
  /**
   * Fazladan deneme sayısı. `attemptCount` 1 ise yeniden deneme yok;
   * toplam - adım sayısı, gerçek retry yükünü verir.
   */
  retryCount: number;
  /** Doğrulama başarısız olup onarılan adım sayısı. */
  repairedStepCount: number;
  failedStepCount: number;
  totalDurationMs: number;
  /** En uzun süren adımın yeteneği — darboğaz avı için. */
  slowestCapability: string | null;
  terminationReason: LoopTerminationReason;
};

export type LoopCredit = {
  /** Başarısızlığın düğümlendiği adımın yeteneği. */
  capability: string | null;
  /** O adım plana nasıl girdi. */
  origin: "router_hint" | "planner_choice" | "unknown";
  /** Kaç denemeden sonra pes edildi. */
  attempts: number;
};

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : 0;
}

export function deriveLoopMetrics(input: {
  steps: LoopStepReport[];
  maxSteps?: number;
  goalVerdict?: string;
}): LoopMetrics {
  const steps = Array.isArray(input.steps) ? input.steps : [];
  let executedStepCount = 0;
  let retryCount = 0;
  let repairedStepCount = 0;
  let failedStepCount = 0;
  let totalDurationMs = 0;
  let slowestCapability: string | null = null;
  let slowestDuration = -1;

  for (const step of steps) {
    const status = text(step.status).toLowerCase();
    const verification = text(step.verificationStatus).toLowerCase();
    const capability = text(step.capability) || text(step.tool) || null;
    const duration = count(step.durationMs);
    // `attemptCount` sözleşmede en az 1; 1 = yeniden deneme yok.
    const attempts = Math.max(1, count(step.attemptCount) || 1);

    const ran = status !== "pending" && status !== "skipped";
    if (ran) executedStepCount += 1;
    retryCount += Math.max(0, attempts - 1);
    if (verification === "repaired") repairedStepCount += 1;
    if (verification === "failed" || status === "failed") failedStepCount += 1;
    totalDurationMs += duration;
    if (duration > slowestDuration) {
      slowestDuration = duration;
      slowestCapability = capability;
    }
  }

  return {
    plannedStepCount: steps.length,
    executedStepCount,
    retryCount,
    repairedStepCount,
    failedStepCount,
    totalDurationMs,
    slowestCapability,
    terminationReason: deriveTerminationReason({
      plannedStepCount: steps.length,
      executedStepCount,
      failedStepCount,
      maxSteps: input.maxSteps,
      goalVerdict: input.goalVerdict,
    }),
  };
}

/**
 * Döngü NEDEN durdu.
 *
 * Sıra önemli: hedef yargısı varsa o otoritedir. Yoksa yapısal sinyallere
 * bakılır. "Hata yok" ile "hedef tuttu" karıştırılmaz — o karışıklık zaten
 * düzeltmeye çalıştığımız asıl sorun.
 */
export function deriveTerminationReason(input: {
  plannedStepCount: number;
  executedStepCount: number;
  failedStepCount: number;
  maxSteps?: number;
  goalVerdict?: string;
}): LoopTerminationReason {
  if (input.plannedStepCount === 0) return "no_plan";
  if (input.goalVerdict === "met") return "goal_reached";
  if (input.failedStepCount > 0) return "step_failure";
  if (
    typeof input.maxSteps === "number" &&
    input.maxSteps > 0 &&
    input.executedStepCount >= input.maxSteps
  ) {
    return "budget_exhausted";
  }
  return "unknown";
}

/**
 * Başarısızlığı bir adıma VE o adımı plana koyan karara bağlar.
 *
 * `routerHints` = iş emrinin `requiredCapabilities` alanı. Patlayan yetenek
 * orada varsa suçlu zincirin başındaki tahmindir; yoksa planlayıcının kendi
 * seçimidir. Bu ayrım olmadan "hangi araç patladı" bilgisi çoğu vakada
 * yanlış yeri işaret eder.
 */
export function assignLoopCredit(input: {
  steps: LoopStepReport[];
  routerHints: string[];
}): LoopCredit | null {
  const steps = Array.isArray(input.steps) ? input.steps : [];
  const hints = new Set(
    (Array.isArray(input.routerHints) ? input.routerHints : [])
      .map((hint) => text(hint).toLowerCase().replaceAll(".", "_"))
      .filter(Boolean),
  );

  for (const step of steps) {
    const status = text(step.status).toLowerCase();
    const verification = text(step.verificationStatus).toLowerCase();
    if (verification !== "failed" && status !== "failed") continue;
    const capability = text(step.capability) || text(step.tool) || null;
    const key = (capability ?? "").toLowerCase().replaceAll(".", "_");
    return {
      capability,
      origin: !capability
        ? "unknown"
        : hints.has(key)
          ? "router_hint"
          : "planner_choice",
      attempts: Math.max(1, count(step.attemptCount) || 1),
    };
  }
  return null;
}

/** Runtime sonucundan adım raporlarını güvenli biçimde çıkarır. */
export function readLoopSteps(result: unknown): LoopStepReport[] {
  const record = readRecord(result);
  const direct = record?.steps;
  if (Array.isArray(direct)) {
    return direct.filter((step): step is LoopStepReport => readRecord(step) !== null);
  }
  const trace = readRecord(record?.taskTrace) ?? readRecord(record?.dispatchWidget);
  const traceSteps = trace?.steps;
  if (Array.isArray(traceSteps)) {
    return traceSteps.filter(
      (step): step is LoopStepReport => readRecord(step) !== null,
    );
  }
  return [];
}
