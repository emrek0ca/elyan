import type { FastifyInstance } from "fastify";
import { AppError } from "../../lib/errors.js";
import type { SharedBrainProvider } from "./runtime.js";
import { buildProviderHeaders } from "./provider-selection.js";

const DEFAULT_PROVIDER_POST_TIMEOUT_MS = 60_000;

/**
 * Runaway guard: aktif akan bir stream'in mutlak üst sınırı. Stall timer'ı
 * sürekli resetleyen ama hiç bitmeyen bir stream provider bug'ında kaynakları
 * sonsuza kadar tutmasın.
 */
const STREAMING_HARD_CAP_MS = 120_000;
const PROVIDER_RATE_WINDOW_MS = 60_000;
const PROVIDER_RATE_KEY_TTL_GRACE_MS = 5_000;

function positiveInt(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0
    ? Math.max(1, Math.trunc(parsed))
    : fallback;
}

function providerRateLimitStoreUnavailable(): AppError {
  return new AppError(
    503,
    "server_brain_unavailable",
    "Yanıt servisi geçici olarak kullanılamıyor. Lütfen biraz sonra yeniden dene.",
    {
      transient: true,
      retrySuggested: true,
      failureClass: "rate_limit_store_unavailable",
    },
  );
}

/**
 * BullMQ limits admitted jobs. This guard also counts every real hosted-model
 * HTTP attempt (including retries and continuation calls) across all workers.
 */
export async function acquireProviderRequestPermit(
  app: FastifyInstance,
  provider: SharedBrainProvider,
  now = Date.now(),
): Promise<void> {
  if (provider !== "groq" && provider !== "gemini") return;

  const store = app.services?.reliability?.store;
  const requireRedis = app.config.RELIABILITY_REDIS_REQUIRED === true;
  if (!store) {
    if (requireRedis) throw providerRateLimitStoreUnavailable();
    return;
  }

  const limit =
    provider === "groq"
      ? positiveInt(app.config.ELYAN_GROQ_RPM_LIMIT, 30)
      : positiveInt(app.config.ELYAN_GEMINI_RPM_LIMIT, 10);
  const windowStartedAt =
    Math.floor(now / PROVIDER_RATE_WINDOW_MS) * PROVIDER_RATE_WINDOW_MS;
  const windowEndsAt = windowStartedAt + PROVIDER_RATE_WINDOW_MS;
  const retryAfterMs = Math.max(250, windowEndsAt - now);
  const key = `provider-rate:${provider}:requests:${windowStartedAt}`;

  let budget: { allowed: boolean; used: number } | null = null;
  try {
    budget = await store.tryConsumeBudget(
      key,
      1,
      limit,
      retryAfterMs + PROVIDER_RATE_KEY_TTL_GRACE_MS,
      requireRedis,
    );
  } catch {
    if (requireRedis) throw providerRateLimitStoreUnavailable();
    return;
  }

  if (budget.allowed) return;
  if (requireRedis && !(await store.ping().catch(() => false))) {
    throw providerRateLimitStoreUnavailable();
  }

  throw new AppError(
    429,
    "rate_limited",
    "Yanıt yeniden deneniyor.",
    {
      transient: true,
      retrySuggested: true,
      failureClass: "rate_limited",
      retryAfterMs,
      retryAfterSeconds: Math.max(1, Math.ceil(retryAfterMs / 1_000)),
    },
  );
}

export function joinProviderUrl(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`.replace(/\/v1\/v1\//g, "/v1/");
}

export async function postJson(
  app: FastifyInstance,
  provider: SharedBrainProvider,
  url: string,
  body: Record<string, unknown>,
  timeoutMs: number = DEFAULT_PROVIDER_POST_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await acquireProviderRequestPermit(app, provider);
    return await fetch(url, {
      method: "POST",
      headers: buildProviderHeaders(app, provider),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timer);
  }
}

export async function postStreamingJson(
  app: FastifyInstance,
  provider: SharedBrainProvider,
  url: string,
  body: Record<string, unknown>,
  timeoutMs: number,
  firstPayloadTimeoutMs: number | null,
  onPayload: (payload: unknown) => void | Promise<void>,
): Promise<Response> {
  const controller = new AbortController();
  // TIMEOUT SEMANTİĞİ: timeoutMs toplam süre değil, son chunk'tan bu yana
  // sessizlik süresidir. Aktif token akışı devam ederken uzun yanıt kesilmez.
  let stallTimer: ReturnType<typeof setTimeout> | null = setTimeout(
    () => controller.abort(),
    timeoutMs,
  );
  const resetStallTimer = () => {
    if (stallTimer) {
      clearTimeout(stallTimer);
    }
    stallTimer = setTimeout(() => controller.abort(), timeoutMs);
  };
  const hardCapTimer = setTimeout(
    () => controller.abort(),
    STREAMING_HARD_CAP_MS,
  );
  let firstPayloadTimer: ReturnType<typeof setTimeout> | null =
    typeof firstPayloadTimeoutMs === "number" && firstPayloadTimeoutMs > 0
      ? setTimeout(() => controller.abort(), firstPayloadTimeoutMs)
      : null;
  try {
    await acquireProviderRequestPermit(app, provider);
    const response = await fetch(url, {
      method: "POST",
      headers: buildProviderHeaders(app, provider),
      body: JSON.stringify(body),
      signal: controller.signal,
    });

    if (!response.ok || !response.body) {
      return response;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      resetStallTimer();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
          continue;
        }
        try {
          if (firstPayloadTimer) {
            clearTimeout(firstPayloadTimer);
            firstPayloadTimer = null;
          }
          const data = trimmed.startsWith("data:")
            ? trimmed.slice(5).trim()
            : trimmed;
          if (!data || data === "[DONE]") {
            continue;
          }
          await onPayload(JSON.parse(data));
        } catch {
          // Ignore malformed provider chunks; final response validity decides fallback.
        }
      }

      if (done) {
        break;
      }
    }

    const trailing = buffer.trim();
    if (trailing) {
      try {
        if (firstPayloadTimer) {
          clearTimeout(firstPayloadTimer);
          firstPayloadTimer = null;
        }
        const data = trailing.startsWith("data:")
          ? trailing.slice(5).trim()
          : trailing;
        if (data && data !== "[DONE]") {
          await onPayload(JSON.parse(data));
        }
      } catch {
        // See malformed chunk note above.
      }
    }

    return response;
  } finally {
    if (stallTimer) {
      clearTimeout(stallTimer);
    }
    clearTimeout(hardCapTimer);
    if (firstPayloadTimer) {
      clearTimeout(firstPayloadTimer);
    }
  }
}
