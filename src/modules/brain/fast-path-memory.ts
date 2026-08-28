import type { FastifyInstance } from "fastify";
import { searchBrainMemory } from "./memory.js";
import { recordStageDuration } from "../../lib/perf-telemetry.js";

/**
 * HIZLI YOL HAFIZASI — "beni tanımıyor" hissinin yapısal kaynağı.
 *
 * Ölçülen durum: mobil sohbetin VARSAYILAN iş yükü `mobile_chat_fast` ve
 * `shouldAugment` hızlı turları bilerek dışarıda bırakıyor. Yani kullanıcının
 * "beni tanıyor mu" diye yargıladığı turların TAMAMINDA modele hiç kalıcı
 * hafıza gitmiyor; üstelik yalın istemde hafıza için bir yuva da yok.
 * Karakter talimatı ne kadar iyi yazılırsa yazılsın, hakkında hiçbir şey
 * bilmediği birine sıcak davranan bir sistem "genel asistan" gibi konuşur.
 *
 * Bu modül o boşluğu ÜÇ SERT KISITLA doldurur:
 *
 *   1. SEMANTİK ALAKA — sözcük deseni yok. Aday hafızalar e5 ile turun
 *      kendisine benzerlik üzerinden elenir. Eşiği geçmeyen hiçbir şey
 *      isteme girmez; "elde var, o hâlde koyalım" yasak.
 *   2. KESİN GECİKME BÜTÇESİ — arama da gömme de saatli. Bütçe dolarsa
 *      hafıza YOK sayılır. İlk token hiçbir koşulda hafıza için beklemez.
 *   3. KESİNLİK ÖNCELİĞİ — bayat, çelişkili ya da geçersiz kılınmış kayıtlar
 *      atılır ve en fazla 3 satır geçer. Yanlış bir hatırlama, hiç
 *      hatırlamamaktan KÖTÜDÜR: kullanıcıyı başkasıyla karıştıran bir asistan
 *      soğuk bir asistandan daha çok güven kaybettirir.
 */

const DEFAULT_BUDGET_MS = 320;
const CANDIDATE_LIMIT = 6;
const MAX_LINES = 3;
/**
 * e5 kosinüs eşiği. Yüksek tutuluyor: bu kapının işi hatırlamayı ÇEKMEK,
 * itmek değil. Eşik düşerse her tura ilgisiz bir "seni tanıyorum" satırı
 * girer ve karakter kazanmak yerine gürültü kazanırız.
 */
const RELEVANCE_THRESHOLD = 0.86;

export type FastPathMemory = {
  lines: string[];
};

function withBudget<T>(promise: Promise<T>, budgetMs: number): Promise<T | null> {
  return new Promise<T | null>((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(null);
    }, budgetMs);
    timer.unref?.();
    promise
      .then((value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      })
      .catch(() => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(null);
      });
  });
}

function compact(value: string, max: number): string {
  return String(value ?? "").replace(/\s+/g, " ").trim().slice(0, max);
}

export async function resolveFastPathMemory(
  app: FastifyInstance,
  input: { userId: string; prompt: string; budgetMs?: number },
): Promise<FastPathMemory | null> {
  const prompt = compact(input.prompt, 500);
  if (!prompt) return null;
  const budgetMs = Math.max(80, input.budgetMs ?? DEFAULT_BUDGET_MS);
  const startedAt = Date.now();

  try {
    const search = await withBudget(
      searchBrainMemory(app, {
        userId: input.userId,
        query: prompt,
        limit: CANDIDATE_LIMIT,
        budgetMs,
      }),
      budgetMs,
    );
    const candidates = (search?.results ?? []).filter(
      (hit) =>
        hit.staleness === "fresh" &&
        hit.conflictStatus === "active" &&
        hit.lifecycleStatus === "active" &&
        hit.deletedAt === null &&
        compact(hit.content, 240).length > 0 &&
        (hit.semanticScore ?? 0) >= RELEVANCE_THRESHOLD,
    );
    if (candidates.length === 0) return null;

    const relevant = candidates
      .sort(
        (left, right) =>
          Number(right.isPinned) - Number(left.isPinned) ||
          (right.semanticScore ?? 0) - (left.semanticScore ?? 0),
      )
      .slice(0, MAX_LINES);
    if (relevant.length === 0) return null;

    return {
      lines: relevant.map((hit) => compact(hit.content, 200)),
    };
  } finally {
    recordStageDuration("chat.fastpath_memory", Date.now() - startedAt);
  }
}
