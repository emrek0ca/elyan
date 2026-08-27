import { AppError } from "../../lib/errors.js";
import { asRecord as readRecord } from "../../lib/record.js";

export type ProviderFailureClass =
  | "rate_limited"
  | "timeout"
  | "unavailable"
  | "invalid_output"
  | "policy_blocked"
  | "rejected"
  | "unknown";

export type ProviderAttemptFailure = {
  provider: string;
  model: string;
  status: number | null;
  failureClass: ProviderFailureClass;
  reason: string;
  retryAfterMs: number | null;
  attempt: number;
};

export type ProviderFailureSummary = {
  failureClass: ProviderFailureClass;
  providerStatus: number | null;
  retryAfterMs: number | null;
  transient: boolean;
  retrySuggested: boolean;
};

const RETRYABLE_PROVIDER_FAILURES: ReadonlySet<ProviderFailureClass> = new Set([
  "rate_limited",
  "timeout",
  "unavailable",
]);

export function summarizeProviderAttemptFailures(
  attempts: ProviderAttemptFailure[],
): ProviderFailureSummary {
  if (attempts.length === 0) {
    return {
      failureClass: "unavailable",
      providerStatus: null,
      retryAfterMs: null,
      transient: true,
      retrySuggested: true,
    };
  }
  const retryableAttempts = attempts.filter((attempt) =>
    RETRYABLE_PROVIDER_FAILURES.has(attempt.failureClass),
  );
  const representative = retryableAttempts.at(-1) ?? attempts.at(-1)!;
  const retryAfterMs = retryableAttempts.reduce<number | null>(
    (current, attempt) =>
      attempt.retryAfterMs == null
        ? current
        : Math.max(current ?? 0, attempt.retryAfterMs),
    null,
  );
  const retrySuggested = retryableAttempts.length > 0;
  return {
    failureClass: representative.failureClass,
    providerStatus: representative.status,
    retryAfterMs,
    transient: retrySuggested,
    retrySuggested,
  };
}

export function providerHttpStatusClass(
  status: number | null,
): "1xx" | "2xx" | "3xx" | "4xx" | "5xx" | "network" {
  if (status == null || !Number.isFinite(status)) return "network";
  const family = Math.trunc(status / 100);
  return family >= 1 && family <= 5
    ? (`${family}xx` as "1xx" | "2xx" | "3xx" | "4xx" | "5xx")
    : "network";
}

export function readProviderRetryAfterMs(headers: Headers): number | null {
  const raw = headers.get("retry-after")?.trim();
  if (!raw) return null;
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.round(seconds * 1_000);
  }
  const at = Date.parse(raw);
  return Number.isFinite(at) ? Math.max(0, at - Date.now()) : null;
}

/** `describeProviderErrorPayload` çıktısının öneki. */
const PROVIDER_ERROR_REASON_PREFIX = "provider_error:";

/**
 * Sağlayıcının HTTP hata gövdesinden kısa, sınıflandırmayı bozmayan bir neden
 * kodu çıkarır.
 *
 * CANLI ARIZA (2026-07-30): Groq iki ayrı modelde tekrar eden 400 döndürüyordu
 * ve telemetride hepsi tek tip `provider_request_failed` görünüyordu — gövde
 * hiçbir yere taşınmadığı için nedeni okumak imkânsızdı. Yalnız `code`/`type`
 * alanını taşırız: serbest metin mesajı sınıflandırma desenlerine ("policy_",
 * "timeout") yanlışlıkla çarpabilir ve yanlış failureClass üretebilir.
 */
export function describeProviderErrorPayload(
  payload: unknown,
  rawText: string,
): string {
  const record = readRecord(payload);
  const error = readRecord(record?.error) ?? record;
  const code =
    typeof error?.code === "string" && error.code.trim()
      ? error.code.trim()
      : typeof error?.type === "string" && error.type.trim()
        ? error.type.trim()
        : "";
  if (code) {
    return `${PROVIDER_ERROR_REASON_PREFIX}${code.slice(0, 80)}`;
  }
  // Gövde JSON değilse (proxy/gateway HTML'i) en azından baş kısmı taşınır;
  // sınıflandırmaya karışmaması için yalnız harf/rakam/altçizgi bırakılır.
  const sanitized = rawText
    .slice(0, 120)
    .replace(/[^a-zA-Z0-9 _-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return sanitized
    ? `${PROVIDER_ERROR_REASON_PREFIX}${sanitized.slice(0, 80)}`
    : "provider_request_failed";
}

function failureClass(input: {
  status: number | null;
  reason: string;
  error: unknown;
}): ProviderFailureClass {
  if (input.status === 429) return "rate_limited";
  // Sağlayıcı isteği reddettiyse sınıf HTTP durumundan gelir; gövdeden gelen
  // serbest metnin desen eşleşmesi ("invalid_request_error" → invalid_output)
  // burada yanlış sınıf üretirdi. Bizim ÜRETTİĞİMİZ neden kodları (ör.
  // `required_turn_envelope_missing`) bu daldan etkilenmez.
  if (input.reason.startsWith(PROVIDER_ERROR_REASON_PREFIX)) {
    if (input.status != null && [408, 425, 500, 502, 503, 504].includes(input.status)) {
      return "unavailable";
    }
    if (input.status != null && input.status >= 400) return "rejected";
  }
  if (input.error instanceof TypeError) return "unavailable";
  if (input.error instanceof DOMException && input.error.name === "AbortError") {
    return "timeout";
  }
  const lowered = input.reason.toLowerCase();
  if (lowered.includes("timeout") || lowered.includes("timed out")) {
    return "timeout";
  }
  if (
    lowered.includes("empty_response") ||
    lowered.includes("empty_stream_response") ||
    lowered.includes("invalid_") ||
    lowered.includes("required_") ||
    lowered.includes("placeholder_") ||
    lowered.includes("reasoning_dump")
  ) {
    return "invalid_output";
  }
  if (
    lowered.includes("policy_blocked") ||
    lowered.includes("policy_") ||
    lowered.includes("private_data_blocked") ||
    lowered.includes("data_usage_not_attested") ||
    lowered.includes("paid_fallback_disabled") ||
    lowered.includes("paid_data_processing_not_attested") ||
    lowered.includes("data_sharing_consent_required")
  ) {
    return "policy_blocked";
  }
  if ([408, 425, 500, 502, 503, 504].includes(input.status ?? 0)) {
    return "unavailable";
  }
  if (input.status != null && input.status >= 400) return "rejected";
  if (
    lowered.includes("fetch") ||
    lowered.includes("network") ||
    lowered.includes("socket") ||
    lowered.includes("econn") ||
    lowered.includes("circuit") ||
    lowered.includes("unavailable")
  ) {
    return "unavailable";
  }
  return "unknown";
}

export function buildProviderAttemptFailure(input: {
  provider: string;
  model: string;
  error: unknown;
  attempt: number;
}): ProviderAttemptFailure {
  const record = readRecord(input.error);
  const details = readRecord(
    input.error instanceof AppError ? input.error.details : null,
  );
  const status =
    typeof record?.status === "number" && Number.isFinite(record.status)
      ? Math.trunc(record.status)
      : input.error instanceof AppError
        ? input.error.statusCode
        : null;
  const retryAfterMs =
    typeof (record?.retryAfterMs ?? details?.retryAfterMs) === "number" &&
    Number.isFinite(record?.retryAfterMs ?? details?.retryAfterMs) &&
    Number(record?.retryAfterMs ?? details?.retryAfterMs) >= 0
      ? Math.trunc(Number(record?.retryAfterMs ?? details?.retryAfterMs))
      : null;
  const reason =
    typeof record?.reason === "string" && record.reason.trim()
      ? record.reason.trim().slice(0, 120)
      : typeof details?.failureClass === "string" &&
          details.failureClass.trim()
        ? details.failureClass.trim().slice(0, 120)
        : input.error instanceof DOMException && input.error.name === "AbortError"
          ? "timeout"
          : input.error instanceof Error
            ? input.error.name.slice(0, 120)
            : typeof input.error === "string"
              ? input.error.slice(0, 120)
              : "provider_request_failed";

  return {
    provider: input.provider,
    model: input.model,
    status,
    failureClass: failureClass({ status, reason, error: input.error }),
    reason,
    retryAfterMs,
    attempt: Math.max(1, Math.trunc(input.attempt)),
  };
}

export function providerRetryDelayMs(randomValue = Math.random()): number {
  const bounded = Math.max(0, Math.min(1, randomValue));
  return 120 + Math.floor(bounded * 180);
}
