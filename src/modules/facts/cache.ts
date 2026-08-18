import type { FastifyInstance } from "fastify";
import type { FactAnswer } from "./types.js";

/**
 * İki katmanlı olgu önbelleği: süreç içi + Redis (`reliability.store`).
 *
 * SWR (stale-while-revalidate) BİLEREK var: hava/kur gibi verilerde 30 sn
 * bayat bir cevabı ANINDA vermek, taze cevabı 400 ms bekletmekten iyidir —
 * kullanıcı farkı görmez, gecikme yarıya iner. Bayat cevap dönerken taze
 * çekim arka planda tetiklenir ve bir sonraki tur güncelini okur.
 *
 * Bayatlık sınırı `ttlMs`'in iki katıdır; onun ötesindeki kayıt kullanılmaz.
 * Böylece "gözlem zamanı" ile kullanıcıya söylenen şey asla saatlerce sapmaz.
 */

type CacheEntry = { answer: FactAnswer; storedAt: number; ttlMs: number };

const MAX_MEMORY_ENTRIES = 256;
const memory = new Map<string, CacheEntry>();
const revalidating = new Set<string>();

function trimMemory(): void {
  while (memory.size > MAX_MEMORY_ENTRIES) {
    const oldest = memory.keys().next();
    if (oldest.done) break;
    memory.delete(oldest.value);
  }
}

function redisKey(key: string): string {
  return `facts:v1:${key}`;
}

function classify(entry: CacheEntry): "fresh" | "stale" | "expired" {
  const age = Date.now() - entry.storedAt;
  if (age <= entry.ttlMs) return "fresh";
  if (age <= entry.ttlMs * 2) return "stale";
  return "expired";
}

export type FactCacheRead = {
  answer: FactAnswer;
  state: "fresh" | "stale";
} | null;

export async function readFactCache(
  app: FastifyInstance,
  key: string,
): Promise<FactCacheRead> {
  const local = memory.get(key);
  if (local) {
    const state = classify(local);
    if (state !== "expired") return { answer: local.answer, state };
    memory.delete(key);
  }
  const store = app.services?.reliability?.store;
  if (!store) return null;
  try {
    const raw = await store.get(redisKey(key));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEntry;
    if (!parsed?.answer || typeof parsed.storedAt !== "number") return null;
    const state = classify(parsed);
    if (state === "expired") return null;
    memory.set(key, parsed);
    trimMemory();
    return { answer: parsed.answer, state };
  } catch {
    return null;
  }
}

export async function writeFactCache(
  app: FastifyInstance,
  key: string,
  answer: FactAnswer,
): Promise<void> {
  const entry: CacheEntry = { answer, storedAt: Date.now(), ttlMs: answer.ttlMs };
  memory.set(key, entry);
  trimMemory();
  const store = app.services?.reliability?.store;
  if (!store) return;
  try {
    await store.set(redisKey(key), JSON.stringify(entry), answer.ttlMs * 2);
  } catch {
    /* önbellek yazımı hiçbir turu düşürmez */
  }
}

/**
 * Bayat kayıt döndürüldüğünde arka planda tek bir tazeleme çalıştırır.
 * Aynı anahtar için ikinci bir tazeleme başlatılmaz (uçuşta tekilleştirme).
 */
export function revalidateFactInBackground(
  key: string,
  refresh: () => Promise<void>,
): void {
  if (revalidating.has(key)) return;
  revalidating.add(key);
  void refresh()
    .catch(() => undefined)
    .finally(() => revalidating.delete(key));
}

export function resetFactCacheForTests(): void {
  memory.clear();
  revalidating.clear();
}
