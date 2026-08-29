import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { collapseWhitespace, foldTurkishDiacritics } from "../../lib/text.js";

/**
 * BİLGİ YOLU İÇİN TEK ÖNBELLEK VE TEK UÇUŞTA-TEKİLLEŞTİRME.
 *
 * Aynı desen kod tabanında üç kez ayrı ayrı yazılmıştı: `facts/cache.ts`
 * (süreç + Redis + SWR), `corpus.ts` (Redis + `WeakMap` inflight) ve
 * `web-grounding.ts` (kendi tazelik penceresi). Üçü de doğru, ama üçünün
 * de eksiği farklı: olgu önbelleğinde uçuşta-tekilleştirme yok, korpusta
 * süreç-içi katman yok, hiçbirinde sorgu normalizasyonu ortak değil.
 *
 * Buradaki iki ilke:
 *
 *   1. UÇUŞTA TEKİLLEŞTİRME ÖNBELLEKTEN ÖNCE GELİR. İki eşzamanlı özdeş
 *      tur (aynı kullanıcının çift dokunuşu, iki cihaz, bir yeniden deneme)
 *      İKİ gömme + İKİ sağlayıcı seçimi ödüyordu. Önbellek burada işe
 *      yaramaz çünkü ilk istek daha yazmamıştır; tekilleştirme yarar.
 *
 *   2. ÖNBELLEK HATASI HİÇBİR TURU DÜŞÜRMEZ. Okuma da yazma da yutulur;
 *      Redis yoksa süreç-içi katman tek başına çalışır.
 *
 * DEĞİŞKEN VERİ BURAYA GİRMEZ. Bu önbellek YÖNLENDİRME KARARINI ve stabil
 * seçim çıktısını tutar — web sonucunu veya sağlayıcı ölçümünü değil.
 * Onların kendi tazelik pencereleri var (`fresh-data-policy`), ve taze veriyi
 * uzun ömürlü bir anahtara yazmak tam da "web sonucunu kalıcı hafızaya
 * yazma" hatasıdır.
 */

type MemoryEntry<T> = { value: T; expiresAt: number };

const MAX_MEMORY_ENTRIES = 512;

const processCache = new Map<string, MemoryEntry<unknown>>();
const inflight = new Map<string, Promise<unknown>>();

function trimProcessCache(): void {
  if (processCache.size <= MAX_MEMORY_ENTRIES) return;
  const now = Date.now();
  for (const [key, entry] of processCache) {
    if (entry.expiresAt <= now) processCache.delete(key);
  }
  while (processCache.size > MAX_MEMORY_ENTRIES) {
    const oldest = processCache.keys().next();
    if (oldest.done) break;
    processCache.delete(oldest.value);
  }
}

/**
 * Sorgu anahtarı: aksansız, boşluk-sıkıştırılmış, küçük harfli metnin özeti.
 * "Dolar kaç TL?" ile "dolar  kac tl?" aynı anahtara düşer — kullanıcıların
 * aynı soruyu farklı yazımla sorması bu yolda kural, istisna değil.
 */
export function knowledgeQueryDigest(query: string): string {
  const normalized = foldTurkishDiacritics(collapseWhitespace(query)).slice(0, 512);
  return createHash("sha256").update(normalized).digest("hex").slice(0, 32);
}

/**
 * AYNI ANAHTARDA TEK ÇALIŞMA. Beklemekte olan bir iş varsa yenisi
 * başlatılmaz; hepsi aynı sözü paylaşır.
 */
export function singleFlight<T>(key: string, load: () => Promise<T>): Promise<T> {
  const pending = inflight.get(key) as Promise<T> | undefined;
  if (pending) return pending;
  const promise = load().finally(() => {
    inflight.delete(key);
  });
  inflight.set(key, promise);
  return promise;
}

export type KnowledgeCacheOptions<T> = {
  key: string;
  ttlMs: number;
  load: () => Promise<T>;
  /**
   * Redis'ten okunan ham JSON'u tipe geri döndürür. `null` dönerse kayıt
   * yok sayılır — şema değiştiğinde eski kayıtların sessizce sızmaması için
   * bu ZORUNLUDUR, `as T` yeterli değildir.
   */
  revive?: (raw: unknown) => T | null;
  /** `false` dönen sonuç yazılmaz (boş/güvenilmez çıktıyı önbelleğe alma). */
  cacheable?: (value: T) => boolean;
};

/**
 * Süreç-içi + Redis okuma-geçişli önbellek, uçuşta tekilleştirmeyle.
 * `app` verilmezse yalnız süreç-içi katman çalışır (test ve işçi yolları).
 */
export async function cachedKnowledge<T>(
  app: FastifyInstance | null | undefined,
  options: KnowledgeCacheOptions<T>,
): Promise<T> {
  const now = Date.now();
  const local = processCache.get(options.key) as MemoryEntry<T> | undefined;
  if (local && local.expiresAt > now) return local.value;
  if (local) processCache.delete(options.key);

  return singleFlight(options.key, async () => {
    const store = app?.services?.reliability?.store;
    if (store && options.revive) {
      try {
        const raw = await store.get(options.key);
        if (raw) {
          const revived = options.revive(JSON.parse(raw) as unknown);
          if (revived !== null) {
            processCache.set(options.key, {
              value: revived,
              expiresAt: Date.now() + options.ttlMs,
            });
            trimProcessCache();
            return revived;
          }
        }
      } catch {
        // Önbellek okunamadıysa kaynak yol çalışır.
      }
    }

    const value = await options.load();
    if (options.cacheable && !options.cacheable(value)) return value;
    processCache.set(options.key, { value, expiresAt: Date.now() + options.ttlMs });
    trimProcessCache();
    if (store && options.revive) {
      await store
        .set(options.key, JSON.stringify(value), options.ttlMs)
        .catch(() => undefined);
    }
    return value;
  });
}

export function resetKnowledgeCacheForTests(): void {
  processCache.clear();
  inflight.clear();
}
