/**
 * DOĞRULANMIŞ YAZMA TERCİHİ — kullanıcıya özel prosedürel hafıza.
 *
 * NEDEN VAR
 * ---------
 * "Raporları hep Masaüstü/Raporlar'a kaydet" bir EPİZOT değil, kalıcı bir
 * tercihtir. `learning_events` içinde `type=preference` olarak zaten
 * saklanıyordu ama hiçbir yürütme kararına bağlanmıyordu: kullanıcı aynı şeyi
 * her seferinde tekrar söylemek zorunda kalıyordu.
 *
 * GÜVENLİK SINIRI — TERCİH YETKİ GENİŞLETEMEZ
 * -------------------------------------------
 * Bir tercih yalnız ZATEN İZİNLİ bir kökün ALTINI işaret edebilir. Yeni bir
 * üst kök açamaz. Aksi hâlde bir hafıza kaydı — ki modelin çıkardığı bir
 * cümleden doğabilir — sessizce `/etc` ya da `~/Library` yazma yetkisi
 * üretebilirdi. Kapı fail-closed: tanımadığı her şeyi düşürür.
 */

import { and, desc, eq, gte } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { learningEvents } from "../../db/schema.js";

/** Tercihin altına inebileceği kökler. Liste work order varsayılanlarıyla aynı. */
export const ALLOWED_WRITE_ROOT_PREFIXES = [
  "workspace",
  "~/Desktop",
  "~/Documents",
  "~/Downloads",
] as const;

const UNSAFE_SEGMENT_PATTERN = /(?:^|\/)\.\.(?:\/|$)/u;
const SAFE_SEGMENT_PATTERN = /^[\p{L}\p{N} ._-]{1,60}$/u;

/**
 * Ham tercih değerini güvenli bir yazma köküne çevirir.
 *
 * `null` dönmesi "bu tercih kullanılamaz" demektir ve sessizce yok sayılır —
 * kullanıcıya bir hata göstermek yerine varsayılan kökler geçerli kalır.
 */
export function parsePreferredWriteRoot(value: unknown): string | null {
  const raw = String(value ?? "").trim().replace(/\\/gu, "/");
  if (!raw || raw.length > 200) return null;
  if (UNSAFE_SEGMENT_PATTERN.test(raw)) return null;

  const normalized = raw.replace(/\/+$/u, "");
  const prefix = ALLOWED_WRITE_ROOT_PREFIXES.find(
    (root) => normalized === root || normalized.startsWith(`${root}/`),
  );
  if (!prefix) return null;

  const remainder = normalized.slice(prefix.length).replace(/^\//u, "");
  if (!remainder) return prefix;

  const segments = remainder.split("/").filter(Boolean);
  // Derin bir yol tercihin niyetini aşar; iki seviye yeter.
  if (segments.length === 0 || segments.length > 2) return null;
  if (!segments.every((segment) => SAFE_SEGMENT_PATTERN.test(segment))) return null;
  return `${prefix}/${segments.join("/")}`;
}

/**
 * Kullanıcının doğrulanmış yazma tercihlerini getirir.
 *
 * Yalnız yüksek güvenli (`confidence >= 75`) ve güncel kayıtlar sayılır: bir
 * kez söylenmiş, doğrulanmamış bir cümle kalıcı bir kural hâline gelmemeli.
 *
 * Fail-open: okunamazsa varsayılan kökler geçerli kalır.
 */
export async function resolvePreferredWriteRoots(
  app: FastifyInstance,
  input: { userId: string; limit?: number; windowDays?: number },
): Promise<string[]> {
  const limit = Math.max(1, Math.min(4, input.limit ?? 2));
  try {
    const since = new Date(
      Date.now() - Math.max(1, input.windowDays ?? 180) * 86_400_000,
    );
    const rows = await app.db
      .select({ value: learningEvents.value, createdAt: learningEvents.createdAt })
      .from(learningEvents)
      .where(
        and(
          eq(learningEvents.userId, input.userId),
          eq(learningEvents.type, "preference"),
          eq(learningEvents.key, "write_root"),
          gte(learningEvents.confidence, 75),
          gte(learningEvents.createdAt, since),
        ),
      )
      .orderBy(desc(learningEvents.createdAt))
      .limit(16);

    const roots: string[] = [];
    for (const row of rows) {
      const root = parsePreferredWriteRoot(row.value);
      if (root && !roots.includes(root)) roots.push(root);
      if (roots.length >= limit) break;
    }
    return roots;
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error) },
      "preferred write roots not resolved",
    );
    return [];
  }
}
