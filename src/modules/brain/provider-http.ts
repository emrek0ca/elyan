import type { FastifyInstance } from "fastify";
import type { SharedBrainProvider } from "./runtime.js";
import { buildProviderHeaders } from "./provider-selection.js";

const DEFAULT_PROVIDER_POST_TIMEOUT_MS = 60_000;

/**
 * Runaway guard: aktif akan bir stream'in mutlak üst sınırı. Stall timer'ı
 * sürekli resetleyen ama hiç bitmeyen bir stream provider bug'ında kaynakları
 * sonsuza kadar tutmasın.
 */
const STREAMING_HARD_CAP_MS = 120_000;

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
