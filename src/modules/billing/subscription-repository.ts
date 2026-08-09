import { eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { subscriptions } from "../../db/schema.js";

/**
 * Abonelik satırının TEK okuyucusu.
 *
 * NEDEN: aynı sorgu üç ayrı dosyada birebir kopyalanmıştı —
 * `auth/service.ts` (`getSubscription`), `billing/service.ts`
 * (`getSubscriptionRowFromDb`) ve `billing/usage-ledger.ts`
 * (`getSubscriptionRow`); `BillingReadDb` tipi de aynı üç dosyada ayrı ayrı
 * tanımlıydı. Kopyaların tehlikesi kod tekrarı değil, SESSİZ SAPMA: biri
 * önbellek, satır kilidi ya da yaşam döngüsü onarımı kazandığında diğerleri
 * eski davranışta kalır ve "kullanıcının planı ekrana göre farklı" sınıfından
 * hatalar çıkar.
 *
 * Kasıtlı olarak İNCE: yalnız satırı döndürür. Plan/yetki türetmesi
 * `subscription-truth.ts`'in, yaşam döngüsü kararları
 * `subscription-lifecycle.ts`'in işidir. Okuma → türetme → karar ayrı
 * katmanlar olarak kalır; karmaşıklık bu üçünün birbirine karışmasından
 * doğuyordu.
 */

/** Yalnız okuma yapan çağıranlar için dar veritabanı arayüzü. */
export type BillingReadDb = Pick<FastifyInstance["db"], "select">;

export type SubscriptionRow = typeof subscriptions.$inferSelect;

/**
 * Kullanıcının abonelik satırı; yoksa `null`.
 *
 * `db` bilinçli olarak dışarıdan geliyor: bir işlem (transaction) içinden
 * çağrıldığında aynı işlemin görünümünü okumak zorundayız, yoksa az önce
 * yazdığımızı okuyamayız.
 */
export async function readSubscriptionRow(
  db: BillingReadDb,
  userId: string,
): Promise<SubscriptionRow | null> {
  const rows = await db
    .select()
    .from(subscriptions)
    .where(eq(subscriptions.userId, userId))
    .limit(1);
  return rows[0] ?? null;
}
