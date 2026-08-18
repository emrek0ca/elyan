import type { FactProviderId } from "./types.js";

/**
 * Sağlayıcı HTTP istemcisi: zaman aşımı + sınırlı gövde + SAĞLAYICI BAŞINA
 * devre kesici.
 *
 * Devre kesici neden şart: ücretsiz katmanlar (özellikle CoinGecko) sert
 * throttle eder. Kesici olmadan 429 alan bir sağlayıcı her turda yeniden
 * denenir; kullanıcı her seferinde zaman aşımını BEKLER ve sonunda yine
 * aramaya düşer — yani hızlanmak için eklenen katman turu yavaşlatır.
 * Kesici açıkken çağrı ANINDA null döner ve tur doğrudan aramaya gider.
 */

const FAILURE_THRESHOLD = 3;
const OPEN_MS = 60_000;
const MAX_BODY_BYTES = 512_000;

type BreakerState = { failures: number; openUntil: number };

const breakers = new Map<FactProviderId, BreakerState>();

function breaker(providerId: FactProviderId): BreakerState {
  let state = breakers.get(providerId);
  if (!state) {
    state = { failures: 0, openUntil: 0 };
    breakers.set(providerId, state);
  }
  return state;
}

export function isFactProviderCircuitOpen(providerId: FactProviderId): boolean {
  return Date.now() < breaker(providerId).openUntil;
}

export function recordFactProviderSuccess(providerId: FactProviderId): void {
  const state = breaker(providerId);
  state.failures = 0;
  state.openUntil = 0;
}

export function recordFactProviderFailure(providerId: FactProviderId): void {
  const state = breaker(providerId);
  state.failures += 1;
  if (state.failures >= FAILURE_THRESHOLD) {
    state.openUntil = Date.now() + OPEN_MS;
    state.failures = 0;
  }
}

export function resetFactProviderCircuitsForTests(): void {
  breakers.clear();
}

export class FactProviderHttpError extends Error {
  public readonly reason: string;

  constructor(reason: string) {
    super(reason);
    this.name = "FactProviderHttpError";
    this.reason = reason;
  }
}

/**
 * Sınırlı JSON okuma. Gövde `MAX_BODY_BYTES`'ı aşarsa okuma kesilir — kötü
 * davranan bir uç noktanın belleği doldurmasına izin verilmez.
 */
async function readBoundedJson(
  response: Response,
  maxBytes: number,
): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) {
    const text = await response.text();
    return JSON.parse(text.slice(0, maxBytes)) as unknown;
  }
  const decoder = new TextDecoder();
  let received = 0;
  let text = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    received += value?.byteLength ?? 0;
    if (received > maxBytes) {
      await reader.cancel().catch(() => undefined);
      throw new FactProviderHttpError("payload_too_large");
    }
    text += decoder.decode(value, { stream: true });
  }
  text += decoder.decode();
  return JSON.parse(text) as unknown;
}

export async function fetchFactJson(input: {
  providerId: FactProviderId;
  url: string;
  timeoutMs: number;
  maxBytes?: number;
}): Promise<Record<string, unknown> | unknown[]> {
  if (isFactProviderCircuitOpen(input.providerId)) {
    throw new FactProviderHttpError("circuit_open");
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(500, input.timeoutMs));
  try {
    const response = await fetch(input.url, {
      signal: controller.signal,
      redirect: "follow",
      headers: {
        accept: "application/json",
        "user-agent": "Elyan/1.0",
      },
    });
    if (!response.ok) {
      recordFactProviderFailure(input.providerId);
      throw new FactProviderHttpError(`http_${response.status}`);
    }
    const payload = await readBoundedJson(response, input.maxBytes ?? MAX_BODY_BYTES);
    if (payload === null || typeof payload !== "object") {
      recordFactProviderFailure(input.providerId);
      throw new FactProviderHttpError("invalid_payload");
    }
    recordFactProviderSuccess(input.providerId);
    return payload as Record<string, unknown> | unknown[];
  } catch (error) {
    if (error instanceof FactProviderHttpError) {
      if (error.reason !== "circuit_open") recordFactProviderFailure(input.providerId);
      throw error;
    }
    recordFactProviderFailure(input.providerId);
    throw new FactProviderHttpError(
      error instanceof Error && error.name === "AbortError" ? "timeout" : "network_error",
    );
  } finally {
    clearTimeout(timer);
  }
}

export function readRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
