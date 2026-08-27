import { asRecord } from "../../lib/record.js";
/**
 * Görev başarısızlıklarını toplu rapora ve öğrenmeye elverişli, makine-okur
 * bir imzaya indirger. Saf fonksiyonlar — DB/ağ yok, kolay test edilir.
 *
 * Kaynaklar (hepsi başarısızlıkta elde):
 *  - task.error        → runtime'ın gönderdiği makine kodu (örn. WORK_ORDER_INVALID)
 *  - task.result       → verification.unverifiedSideEffects (patlayan araç), error.code
 *  - task.payload      → desktopContext.requiresCapabilities (görev tipi imzası)
 */

const MAX_CAPABILITIES = 8;
const MAX_CODE_LENGTH = 64;

export type TaskFailureSignature = {
  /** Kararlı, düşük-kardinaliteli slug — gruplama anahtarı. */
  errorCode: string;
  /** Etkisi doğrulanamayan ilk araç (varsa). */
  failedTool: string | null;
  /** Görevin talep ettiği yetenekler — "hangi görev tipi patlıyor". */
  capabilities: string[];
};

/**
 * Serbest metin ya da SCREAMING_SNAKE kodu, kararlı bir slug'a çevirir.
 * Boşsa "unknown" döner.
 */
export function normalizeFailureCode(raw: unknown): string {
  const slug = String(raw ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, MAX_CODE_LENGTH)
    .replace(/_+$/g, "");
  return slug || "unknown";
}

function extractCapabilities(payload: Record<string, unknown> | null): string[] {
  if (!payload) {
    return [];
  }
  const candidates: unknown[] = [];
  const desktopContext = asRecord(payload.desktopContext);
  if (desktopContext) {
    candidates.push(desktopContext.requiresCapabilities);
  }
  const workOrder = asRecord(payload.desktopWorkOrder);
  if (workOrder) {
    candidates.push(workOrder.requiredCapabilities);
  }
  candidates.push(payload.requiresCapabilities, payload.requiredCapabilities);

  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      const cleaned = Array.from(
        new Set(
          candidate
            .map((value) => String(value ?? "").trim().toLowerCase())
            .filter(Boolean),
        ),
      ).slice(0, MAX_CAPABILITIES);
      if (cleaned.length > 0) {
        return cleaned;
      }
    }
  }
  return [];
}

function extractFailedTool(result: Record<string, unknown> | null): string | null {
  if (!result) {
    return null;
  }
  const verification = asRecord(result.verification);
  const unverified = verification?.unverifiedSideEffects;
  if (Array.isArray(unverified)) {
    for (const entry of unverified) {
      const tool = String(entry ?? "").trim();
      if (tool) {
        return tool.toLowerCase();
      }
    }
  }
  return null;
}

/**
 * Başarısız bir görevden gruplanabilir imza türetir. `result` verilmezse
 * (ucuz rapor sorgusu blob okumadan çalışır) failedTool null kalır.
 */
export function deriveTaskFailureSignature(input: {
  error?: unknown;
  result?: unknown;
  payload?: unknown;
}): TaskFailureSignature {
  const result = asRecord(input.result);
  const payload = asRecord(input.payload);

  let rawCode = String(input.error ?? "").trim();
  if (!rawCode && result) {
    const resultError = asRecord(result.error);
    rawCode = String(resultError?.code ?? "").trim();
  }
  const failedTool = extractFailedTool(result);
  if (!rawCode) {
    const verification = asRecord(result?.verification);
    if (verification?.status === "failed" || failedTool) {
      rawCode = "unverified_side_effect";
    }
  }

  return {
    errorCode: normalizeFailureCode(rawCode),
    failedTool,
    capabilities: extractCapabilities(payload),
  };
}

export type TaskFailureAggregateRow = {
  errorCode: string;
  count: number;
  capabilities: { capability: string; count: number }[];
  sampleTaskIds: string[];
};

/**
 * Başarısız görev imzalarını hata koduna göre gruplar; her grupta en sık
 * yetenekleri ve örnek görev kimliklerini toplar. Sonuç azalan sayıya göre
 * sıralı — "hangi görev tipi en çok patlıyor" listesini verir.
 */
export function aggregateTaskFailures(
  rows: { taskId: string; signature: TaskFailureSignature }[],
  options: { sampleLimit?: number; topCapabilities?: number } = {},
): TaskFailureAggregateRow[] {
  const sampleLimit = options.sampleLimit ?? 5;
  const topCapabilities = options.topCapabilities ?? 5;

  const buckets = new Map<
    string,
    { count: number; capabilityCounts: Map<string, number>; sampleTaskIds: string[] }
  >();

  for (const { taskId, signature } of rows) {
    let bucket = buckets.get(signature.errorCode);
    if (!bucket) {
      bucket = { count: 0, capabilityCounts: new Map(), sampleTaskIds: [] };
      buckets.set(signature.errorCode, bucket);
    }
    bucket.count += 1;
    if (bucket.sampleTaskIds.length < sampleLimit) {
      bucket.sampleTaskIds.push(taskId);
    }
    for (const capability of signature.capabilities) {
      bucket.capabilityCounts.set(capability, (bucket.capabilityCounts.get(capability) ?? 0) + 1);
    }
  }

  return Array.from(buckets.entries())
    .map(([errorCode, bucket]) => ({
      errorCode,
      count: bucket.count,
      capabilities: Array.from(bucket.capabilityCounts.entries())
        .map(([capability, count]) => ({ capability, count }))
        .sort((a, b) => b.count - a.count || a.capability.localeCompare(b.capability))
        .slice(0, topCapabilities),
      sampleTaskIds: bucket.sampleTaskIds,
    }))
    .sort((a, b) => b.count - a.count || a.errorCode.localeCompare(b.errorCode));
}
