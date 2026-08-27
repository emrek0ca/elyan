import type { FastifyInstance } from "fastify";
import { AppError } from "../../lib/errors.js";
import type { SharedBrainProvider } from "./runtime.js";
import {
  buildProviderHeaders,
  getConfiguredProviderApiKey,
  getConfiguredProviderBaseUrl,
  getConfiguredProviderKeySlot,
  getConfiguredProviderApiKeys,
} from "./provider-selection.js";

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

function providerRequestUrl(
  provider: SharedBrainProvider,
  url: string,
  streaming: boolean,
): string {
  if (
    provider === "gemini" &&
    streaming &&
    url.includes("/interactions") &&
    !url.includes("alt=sse")
  ) {
    return `${url}${url.includes("?") ? "&" : "?"}alt=sse`;
  }
  return url;
}

function providerRequestHeaders(
  app: FastifyInstance,
  provider: SharedBrainProvider,
  url: string,
  requestKeySeed?: string,
): Record<string, string> {
  const headers = buildProviderHeaders(app, provider, requestKeySeed);
  if (provider !== "gemini" || !url.includes("/interactions")) {
    return headers;
  }

  const authorization = headers.Authorization;
  if (authorization?.startsWith("Bearer ")) {
    headers["x-goog-api-key"] = authorization.slice("Bearer ".length);
    delete headers.Authorization;
  }
  if (url.includes("alt=sse")) {
    headers.Accept = "text/event-stream";
  }
  // Required by the current native multimodal Interactions REST contract.
  headers["Api-Revision"] = "2026-05-20";
  return headers;
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
  requestKeySeed?: string,
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
  const keyCount =
    provider === "groq" || provider === "gemini"
      ? Math.max(1, getConfiguredProviderApiKeys(app, provider).length)
      : 1;
  const keySlot =
    provider === "groq" || provider === "gemini"
      ? getConfiguredProviderKeySlot(app, provider, requestKeySeed)
      : 0;
  const keyScope = keyCount > 1 ? `:key-${keySlot}` : "";
  const key = `provider-rate:${provider}${keyScope}:requests:${windowStartedAt}`;

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

/**
 * Uzak sağlayıcı bağlantılarını AÇILIŞTA kurar.
 *
 * ÖLÇÜM (yerel koşu): ilk sohbet isteğinin kabul gecikmesi 1900–2000 ms,
 * sonrakiler 60–160 ms. Aradaki farkın büyük kısmı model değil TAŞIMA: DNS
 * çözümü, TCP el sıkışması ve TLS anlaşması ilk gerçek kullanıcı turunda
 * yapılıyor. Bu bedeli ödeyen, o gün ilk yazan kullanıcı oluyor.
 *
 * Isıtma kasıtlı olarak ZARARSIZ bir GET'tir: model çağırmaz, token
 * harcamaz, kota tüketmez. Başarısız olması da önemsizdir — amaç yanıt
 * almak değil, soketi açmak. Bu yüzden her hata yutulur ve sunucunun
 * açılışını hiçbir koşulda geciktirmez.
 */
export async function warmProviderConnections(
  app: FastifyInstance,
  providers: ReadonlyArray<"groq" | "gemini" | "openai">,
  timeoutMs = 3_000,
): Promise<Array<{ provider: string; warmed: boolean }>> {
  const unique = [...new Set(providers)];
  return Promise.all(
    unique.map(async (provider) => {
      const baseUrl = getConfiguredProviderBaseUrl(app, provider);
      const apiKey = getConfiguredProviderApiKey(app, provider);
      if (!baseUrl || !apiKey) {
        return { provider, warmed: false };
      }
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), timeoutMs);
      try {
        await fetch(`${baseUrl.replace(/\/+$/, "")}/models`, {
          method: "GET",
          headers: providerRequestHeaders(app, provider, baseUrl),
          signal: controller.signal,
        });
        return { provider, warmed: true };
      } catch {
        // Soket açıldıysa iş görüldü; cevabın kendisi umursanmaz.
        return { provider, warmed: false };
      } finally {
        clearTimeout(timer);
      }
    }),
  );
}

export async function postJson(
  app: FastifyInstance,
  provider: SharedBrainProvider,
  url: string,
  body: Record<string, unknown>,
  timeoutMs: number = DEFAULT_PROVIDER_POST_TIMEOUT_MS,
  requestKeySeed?: string,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    await acquireProviderRequestPermit(app, provider, Date.now(), requestKeySeed);
    return await fetch(url, {
      method: "POST",
      headers: providerRequestHeaders(app, provider, url, requestKeySeed),
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
  requestKeySeed?: string,
): Promise<Response> {
  const controller = new AbortController();
  // TIMEOUT SEMANTİĞİ: timeoutMs toplam süre değil, son chunk'tan bu yana
  // sessizlik süresidir. Aktif token akışı devam ederken uzun yanıt kesilmez.
  let stallTimer: ReturnType<typeof setTimeout> | null = null;
  const resetStallTimer = () => {
    if (stallTimer) {
      clearTimeout(stallTimer);
    }
    stallTimer = setTimeout(() => controller.abort(), timeoutMs);
  };
  let hardCapTimer: ReturnType<typeof setTimeout> | null = null;
  let firstPayloadTimer: ReturnType<typeof setTimeout> | null = null;
  try {
    await acquireProviderRequestPermit(app, provider, Date.now(), requestKeySeed);
    // Redis/provider admission is outside the model first-token budget. Start
    // network and stream timers only after this request owns provider capacity;
    // otherwise a busy rate-limit store can abort the request before fetch().
    resetStallTimer();
    hardCapTimer = setTimeout(() => controller.abort(), STREAMING_HARD_CAP_MS);
    firstPayloadTimer =
      typeof firstPayloadTimeoutMs === "number" && firstPayloadTimeoutMs > 0
        ? setTimeout(() => controller.abort(), firstPayloadTimeoutMs)
        : null;
    const requestUrl = providerRequestUrl(provider, url, true);
    const response = await fetch(requestUrl, {
      method: "POST",
      headers: providerRequestHeaders(app, provider, requestUrl, requestKeySeed),
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
          const data = trimmed.startsWith("data:")
            ? trimmed.slice(5).trim()
            : trimmed;
          if (!data || data === "[DONE]") {
            continue;
          }
          const payload = JSON.parse(data);
          if (firstPayloadTimer) {
            clearTimeout(firstPayloadTimer);
            firstPayloadTimer = null;
          }
          await onPayload(payload);
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
        const data = trailing.startsWith("data:")
          ? trailing.slice(5).trim()
          : trailing;
        if (data && data !== "[DONE]") {
          const payload = JSON.parse(data);
          if (firstPayloadTimer) {
            clearTimeout(firstPayloadTimer);
            firstPayloadTimer = null;
          }
          await onPayload(payload);
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
    if (hardCapTimer) clearTimeout(hardCapTimer);
    if (firstPayloadTimer) {
      clearTimeout(firstPayloadTimer);
    }
  }
}
