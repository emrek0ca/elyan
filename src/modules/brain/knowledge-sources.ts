import type { FastifyInstance } from "fastify";
import {
  ELYAN_BRAIN_CORPUS_VERSION,
  selectBrainCorpusDomains,
  type BrainCorpusDomain,
  type BrainCorpusSelection,
} from "./corpus.js";
import { cachedKnowledge, knowledgeQueryDigest } from "./knowledge-cache.js";
import { embedQueryForStorage } from "./semantic-embedder.js";
import { FACT_PROVIDERS } from "../facts/registry.js";
import { selectFactProviders, type FactSelection } from "../facts/select.js";

/**
 * TİPLİ KAYNAK YOKLAMASI — YÖNLENDİRİCİNİN İKİNCİ FAZI.
 *
 * Faz 1 (`planKnowledgeRoute`) hiçbir dış kaynağa bakmadan kapanabilen
 * turları kapatır. Kapanmayan turda sorulacak tek soru şudur: BU SORUYA
 * TİPLİ BİR KAYNAK CEVAP VEREBİLİR Mİ? — önce sağlayıcı kaydı, sonra
 * stabil korpus. İkisi de hayır derse açık web'e sıra gelir.
 *
 * Bu modül o yoklamanın TEK yeridir ve üç şeyi düzeltir:
 *
 *   1. GÖMME BİR KEZ. İki seçici de aynı sorgu vektörünü ister; eskiden
 *      vektör çağıran tarafta hesaplanıp elden geçiriliyordu ve seçim
 *      önbelleğe alınmadığı için AYNI SORU her turda yeniden gömülüyordu.
 *
 *   2. SEÇİM ÖNBELLEĞE ALINIR. Önbelleğe alınan şey sağlayıcı KİMLİKLERİ ve
 *      korpus ALANLARIDIR — ölçüm değil, karar. Karar sorgu metnine ve
 *      katalog sürümüne bağlıdır; ikisi de anahtarın içindedir. Sağlayıcının
 *      DÖNDÜRDÜĞÜ veri (kur, hava) buraya asla girmez; onun tazelik penceresi
 *      `facts/cache.ts` içindedir.
 *
 *   3. UÇUŞTA TEKİLLEŞTİRME. Aynı soruyu aynı anda soran iki tur tek gömme
 *      ve tek seçim öder.
 *
 * VEKTÖR TEMBELDİR. Seçim önbellekten geldiyse hiç gömme yapılmaz; aşağı
 * akıştaki çağrılara `undefined` geçilir ve onlar GERÇEKTEN ihtiyaç duyarsa
 * kendi vektörünü hesaplar. `null` geçmek onları kalıcı olarak karma-vektör
 * yedeğine düşürürdü — sessiz bir kalite kaybı.
 */

const SELECTION_CACHE_TTL_MS = 6 * 60 * 60_000;
const SELECTION_EMBED_TIMEOUT_MS = 2_500;
const PROVIDER_CATALOG_VERSION = "facts.v1";

type CachedSelection = {
  providerIds: string[];
  providerScores: number[];
  corpusDomains: BrainCorpusDomain[];
  corpusScores: number[];
  corpusSource: BrainCorpusSelection["source"];
};

export type TypedSourceProbe = {
  providerShortlist: FactSelection[];
  corpusSelections: BrainCorpusSelection[];
  /**
   * Bu turda gerçekten hesaplanan vektör. Önbellek isabetinde `undefined`
   * kalır ve aşağı akış kendi kararını verir.
   */
  queryVector: number[] | null | undefined;
  cacheState: "hit" | "miss";
};

function selectionCacheKey(query: string, probeCorpus: boolean): string {
  return `brain:knowledge-selection:v1:${PROVIDER_CATALOG_VERSION}:${ELYAN_BRAIN_CORPUS_VERSION}:${
    probeCorpus ? "pc" : "np"
  }:${knowledgeQueryDigest(query)}`;
}

function reviveSelection(raw: unknown): CachedSelection | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  if (!Array.isArray(record.providerIds) || !Array.isArray(record.corpusDomains)) {
    return null;
  }
  const providerIds = record.providerIds.filter(
    (id): id is string => typeof id === "string",
  );
  // Katalogdan düşmüş bir sağlayıcı kimliği kaydı GEÇERSİZ kılar; yarım
  // kısa listeyle devam etmek sistematik olarak yanlış sağlayıcı seçtirir
  // (bkz. `facts/select.ts` içindeki eksik-katalog notu).
  if (providerIds.some((id) => !FACT_PROVIDERS.some((provider) => provider.id === id))) {
    return null;
  }
  return {
    providerIds,
    providerScores: Array.isArray(record.providerScores)
      ? (record.providerScores as number[])
      : [],
    corpusDomains: record.corpusDomains.filter(
      (domain): domain is BrainCorpusDomain => typeof domain === "string",
    ),
    corpusScores: Array.isArray(record.corpusScores)
      ? (record.corpusScores as number[])
      : [],
    corpusSource: record.corpusSource === "registry" ? "registry" : "semantic",
  };
}

function hydrateSelection(cached: CachedSelection): {
  providerShortlist: FactSelection[];
  corpusSelections: BrainCorpusSelection[];
} {
  return {
    providerShortlist: cached.providerIds.flatMap((id, index) => {
      const provider = FACT_PROVIDERS.find((candidate) => candidate.id === id);
      return provider ? [{ provider, score: cached.providerScores[index] ?? 0 }] : [];
    }),
    corpusSelections: cached.corpusDomains.map((domain, index) => ({
      domain,
      score: cached.corpusScores[index] ?? 0,
      source: cached.corpusSource,
    })),
  };
}

export async function probeTypedKnowledgeSources(
  app: FastifyInstance | null | undefined,
  input: {
    query: string;
    probeCorpus: boolean;
    logger?: FastifyInstance["log"];
  },
): Promise<TypedSourceProbe> {
  let computedVector: number[] | null | undefined;
  let cacheState: TypedSourceProbe["cacheState"] = "hit";

  const cached = await cachedKnowledge<CachedSelection>(app, {
    key: selectionCacheKey(input.query, input.probeCorpus),
    ttlMs: SELECTION_CACHE_TTL_MS,
    revive: reviveSelection,
    load: async () => {
      cacheState = "miss";
      computedVector = await embedQueryForStorage(
        input.query,
        input.logger,
        "knowledge:query",
        SELECTION_EMBED_TIMEOUT_MS,
      ).catch(() => null);
      const [providerShortlist, corpusSelections] = await Promise.all([
        selectFactProviders({
          prompt: input.query,
          queryVector: computedVector,
          logger: input.logger,
        }).catch(() => [] as FactSelection[]),
        input.probeCorpus
          ? selectBrainCorpusDomains({
              prompt: input.query,
              queryVector: computedVector,
              logger: input.logger,
            }).catch(() => [] as BrainCorpusSelection[])
          : Promise.resolve([] as BrainCorpusSelection[]),
      ]);
      return {
        providerIds: providerShortlist.map((entry) => entry.provider.id),
        providerScores: providerShortlist.map((entry) => entry.score),
        corpusDomains: corpusSelections.map((entry) => entry.domain),
        corpusScores: corpusSelections.map((entry) => entry.score),
        corpusSource: corpusSelections[0]?.source ?? "semantic",
      };
    },
    // Gömme başarısızken üretilen BOŞ seçim önbelleğe ALINMAZ. Alınsaydı
    // ONNX işçisinin bir anlık kesintisi altı saat boyunca her turu tipli
    // kaynaksız bırakırdı — sessiz ve uzun ömürlü bir kalite kaybı.
    cacheable: (value) =>
      computedVector != null ||
      value.providerIds.length > 0 ||
      value.corpusDomains.length > 0,
  });

  return { ...hydrateSelection(cached), queryVector: computedVector, cacheState };
}
