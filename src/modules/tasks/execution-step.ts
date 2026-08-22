/**
 * ADIM SÖZLEŞMESİ — cihazlar arası yürütmenin ortak dili.
 *
 * Notion §4 ve §8. İki ayrı karar birbirine bağlanmamalı:
 *   capability = browser_automation      (NE yapılacak)
 *   device     = desktop                 (NEREDE yapılacak)
 *
 * Bugünkü `executionPlan` yalnız
 *   Array<"mobile_local" | "server_brain" | "desktop_runtime">
 * yani adım başına cihaz TAŞIMIYOR. "Bilgisayarımdaki faturayı bul ve telefona
 * gönder" isteğini cihazlara bölmek bu şekille mümkün değil.
 *
 * ESKİ ALAN KALDIRILMADI. `executionPlan` yüzey listesini taşımaya devam
 * ediyor; `executionSteps` onun yanına ekleniyor. Bu projede çalışan bir yolu
 * yeni bir yolla değiştirmek defalarca regresyon üretti — yeni şekil önce
 * yanında yaşar, ölçülür, sonra tek kaynak olur.
 */

export type ExecutionDevice = "desktop" | "mobile" | "control-plane";

export type ExecutionStep = {
  stepId: string;
  /**
   * Adımın çalışacağı cihaz. Belirsizse `undefined` — koordinatör çözer.
   * "Bilmiyorum" ile "control-plane" AYNI ŞEY DEĞİL.
   */
  device?: ExecutionDevice;
  capability: string;
  dependsOn?: string[];
  input?: unknown;
};

/**
 * TÜM araç çıktıları bu sözleşmeye uyar (Notion §8).
 *
 * Amaç tek: bir adımın çıktısı BAŞKA CİHAZDAKİ adımın girdisi olabilsin.
 * Bugün her araç kendi şeklini döndürüyor ve zincirleme ancak aynı cihazda,
 * elle yazılmış eşleştirmelerle mümkün oluyor.
 */
export type ToolError = {
  code: string;
  message: string;
  /** Yeniden denemek güvenli mi? Bilinmiyorsa `undefined` bırakılır. */
  retryable?: boolean;
};

export type ToolArtifactRef = {
  artifactId: string;
  kind: string;
  /**
   * Artefaktın DURDUĞU yer. Local-first kuralı (Notion §7) bunun üzerine
   * kurulur: özel veri cihazda kalır, kontrol düzlemine yalnız referans ve
   * gerekli sonuç gider.
   */
  location: ExecutionDevice;
  name?: string;
  mime?: string;
};

export type ToolObservation = {
  kind: string;
  detail: string;
};

export type ToolResult = {
  success: boolean;
  output?: unknown;
  artifacts?: ToolArtifactRef[];
  error?: ToolError;
  observations?: ToolObservation[];
  metrics?: {
    latencyMs: number;
    retries: number;
  };
};

const DEVICES: ReadonlySet<string> = new Set<ExecutionDevice>([
  "desktop",
  "mobile",
  "control-plane",
]);

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/**
 * Serbest biçimli adım verisini sözleşmeye çevir.
 *
 * Geçersiz adım SESSİZCE düzeltilmez, ATILIR. Yarım bir adımı "tamamlamak"
 * uydurma üretir; eksik adım hiç olmayan adımdan tehlikelidir.
 */
export function normalizeExecutionSteps(value: unknown): ExecutionStep[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  const steps: ExecutionStep[] = [];
  for (const raw of value) {
    const record = readRecord(raw);
    if (!record) continue;
    const capability = String(record.capability ?? "").trim();
    if (!capability) continue;
    let stepId = String(record.stepId ?? record.id ?? "").trim();
    if (!stepId || seen.has(stepId)) stepId = `step_${steps.length + 1}`;
    seen.add(stepId);
    const device = String(record.device ?? "").trim();
    const dependsOn = Array.isArray(record.dependsOn)
      ? record.dependsOn.map((item) => String(item ?? "").trim()).filter(Boolean)
      : [];
    steps.push({
      stepId,
      capability,
      ...(DEVICES.has(device) ? { device: device as ExecutionDevice } : {}),
      ...(dependsOn.length > 0 ? { dependsOn } : {}),
      ...(record.input !== undefined ? { input: record.input } : {}),
    });
  }
  // Sarkan bağımlılık temizlenir: olmayan adıma bağlı kalmak yürütmeyi kilitler.
  const validIds = new Set(steps.map((step) => step.stepId));
  return steps.map((step) => {
    const dependsOn = (step.dependsOn ?? []).filter(
      (id) => validIds.has(id) && id !== step.stepId,
    );
    return dependsOn.length > 0 ? { ...step, dependsOn } : { ...step, dependsOn: undefined };
  });
}

/**
 * Herhangi bir araç çıktısını standart sözleşmeye çevir.
 *
 * Bilinmeyen şekil `success:false` olarak DEĞİL, çıktısı taşınan bir sonuç
 * olarak döner — "şekli tanımadım" ile "iş başarısız" ayrı şeylerdir.
 */
export function toToolResult(value: unknown): ToolResult {
  const record = readRecord(value);
  if (!record) return { success: value !== undefined && value !== null, output: value };

  const explicitSuccess =
    typeof record.success === "boolean"
      ? record.success
      : typeof record.ok === "boolean"
        ? record.ok
        : undefined;
  const errorRecord = readRecord(record.error);
  const errorCode = String(record.errorCode ?? errorRecord?.code ?? "").trim();
  const errorMessage = String(errorRecord?.message ?? record.errorMessage ?? "").trim();
  const success = explicitSuccess ?? !(errorCode || errorMessage);

  const artifacts = Array.isArray(record.artifacts)
    ? record.artifacts.flatMap((item): ToolArtifactRef[] => {
        const artifact = readRecord(item);
        const artifactId = String(artifact?.artifactId ?? artifact?.id ?? "").trim();
        if (!artifactId) return [];
        const location = String(artifact?.location ?? "").trim();
        return [
          {
            artifactId,
            kind: String(artifact?.kind ?? artifact?.type ?? "unknown"),
            location: DEVICES.has(location) ? (location as ExecutionDevice) : "desktop",
            ...(artifact?.name ? { name: String(artifact.name) } : {}),
            ...(artifact?.mime ? { mime: String(artifact.mime) } : {}),
          },
        ];
      })
    : [];

  const metricsRecord = readRecord(record.metrics);
  const latencyMs = Number(metricsRecord?.latencyMs ?? record.latencyMs);
  const retries = Number(metricsRecord?.retries ?? record.retries);

  return {
    success,
    ...(record.output !== undefined ? { output: record.output } : {}),
    ...(artifacts.length > 0 ? { artifacts } : {}),
    ...(!success && (errorCode || errorMessage)
      ? {
          error: {
            code: errorCode || "unknown_error",
            message: errorMessage || errorCode,
            ...(typeof errorRecord?.retryable === "boolean"
              ? { retryable: errorRecord.retryable }
              : {}),
          },
        }
      : {}),
    ...(Number.isFinite(latencyMs) || Number.isFinite(retries)
      ? {
          metrics: {
            latencyMs: Number.isFinite(latencyMs) ? latencyMs : 0,
            retries: Number.isFinite(retries) ? retries : 0,
          },
        }
      : {}),
  };
}
