import type { FastifyBaseLogger } from "fastify";
import { embedTextsForStorage, embedQueryForStorage } from "../brain/semantic-embedder.js";
import { FACT_PROVIDERS } from "./registry.js";
import type { FactProvider } from "./types.js";

/**
 * SAĞLAYICI SEÇİMİ — e5 ile, regex ile değil.
 *
 * Her sağlayıcının niyet ifadeleri bir kez gömülür (süreç ömrü boyunca
 * önbellekte) ve kullanıcı turu ile kosinüs benzerliği ölçülür. İki kapı var:
 *
 *   1. MUTLAK EŞİK — top-1 benzerliği bunun altındaysa hiçbir sağlayıcı
 *      seçilmez. e5 normalize vektör döndürdüğü için bu skor karşılaştırılabilir.
 *   2. KISA LİSTE — "hava durumu" ile "hava kalitesi" e5 uzayında birbirine
 *      ÇOK yakındır; tek bir top-1 kararına bağlanmak kırılgandır. Bunun
 *      yerine eşiği geçen ve top-1'e yakın en fazla iki aday sırayla denenir;
 *      ilk GERÇEK cevap üreten kazanır. Sağlayıcılar turda kendi varlıklarını
 *      bulamazsa zaten `null` döndüğü için bu, kullanıcının sormadığı veriyi
 *      vermeye yol açmaz — yalnız yakın-beraberlikte çıkmaz sokağı kaldırır.
 *
 * Kısa liste tek adaya İNDİRGENMEZ: canlı ölçümde (regresyon testi) "hava
 * durumu" turu top-1'de hava KALİTESİ sağlayıcısını seçebiliyor; eski katı
 * top-1 kuralında o tur hiç cevaplanamıyordu.
 *
 * e5 çalışmıyorsa (worker kapalı/cooldown) seçim YAPILMAZ; çağıran taraf
 * yalnızca mevcut `FreshDataPolicy.domain` sinyaline bağlı yedek yolu kullanır.
 * Böylece bu modül ikinci bir sözcük-deseni sahibi hâline gelmez.
 */

const ABSOLUTE_THRESHOLD = 0.82;
/** Top-1'e bu kadar yakın adaylar da denenir. */
const SHORTLIST_WINDOW = 0.03;
const SHORTLIST_MAX = 2;

let intentVectors: Array<{ provider: FactProvider<unknown>; vectors: number[][] }> | null = null;
let intentVectorsPromise: Promise<void> | null = null;

function cosine(left: number[], right: number[]): number {
  let dot = 0;
  for (let index = 0; index < left.length && index < right.length; index += 1) {
    dot += left[index] * right[index];
  }
  return dot;
}

async function ensureIntentVectors(
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
): Promise<void> {
  if (intentVectors) return;
  if (!intentVectorsPromise) {
    intentVectorsPromise = (async () => {
      const built: Array<{ provider: FactProvider<unknown>; vectors: number[][] }> = [];
      for (const provider of FACT_PROVIDERS) {
        const vectors = await embedTextsForStorage(
          provider.intents,
          logger,
          `facts:intents:${provider.id}`,
        );
        if (!vectors) {
          // Tek bir sağlayıcı gömülemezse katalog EKSİK olur; yarım katalogla
          // seçim yapmak sistematik olarak yanlış sağlayıcıyı seçtirir.
          intentVectorsPromise = null;
          return;
        }
        built.push({ provider, vectors });
      }
      intentVectors = built;
    })();
  }
  await intentVectorsPromise;
}

export type FactSelection = {
  provider: FactProvider<unknown>;
  score: number;
};

export async function selectFactProviders(input: {
  prompt: string;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<FactSelection[]> {
  await ensureIntentVectors(input.logger);
  if (!intentVectors) return [];
  const queryVector = await embedQueryForStorage(input.prompt, input.logger, "facts:query");
  if (!queryVector) return [];

  const scored = intentVectors
    .map(({ provider, vectors }) => ({
      provider,
      score: vectors.reduce((best, vector) => Math.max(best, cosine(queryVector, vector)), -1),
    }))
    .sort((left, right) => right.score - left.score);

  const top = scored[0];
  if (!top || top.score < ABSOLUTE_THRESHOLD) return [];
  return scored
    .filter((entry) => entry.score >= top.score - SHORTLIST_WINDOW)
    .slice(0, SHORTLIST_MAX);
}

export function resetFactSelectionForTests(): void {
  intentVectors = null;
  intentVectorsPromise = null;
}
