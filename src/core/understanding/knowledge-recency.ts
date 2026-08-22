import {
  embedQueryForStorage,
  embedTextsForStorage,
} from "../../modules/brain/semantic-embedder.js";

/**
 * BİLGİ TAZELİĞİ EKSENİ — "bunu model zaten biliyor mu, yoksa canlı veri mi
 * gerekiyor?"
 *
 * NEDEN GEREKLİ
 * -------------
 * Kullanıcının doğrudan tarif ettiği sorun: "kediler hakkında rapor" gibi genel
 * bilgi görevinde sistem tarayıcıyı açıp Wikipedia'ya gitmeye kalkıyordu — en
 * kırılgan yol, üstelik modelin zaten bildiği bir konu için. Buna karşılık
 * "2026 enflasyon rakamları" gerçekten canlı kaynak ister; modelin kendi
 * bilgisiyle yazması UYDURMA üretir.
 *
 * Aynı karar iki hatayı da doğurabiliyor:
 *   gereksiz araştırma → yavaş ve kırılgan
 *   eksik araştırma    → uydurma sayı/tarih
 *
 * NEDEN REGEX DEĞİL
 * -----------------
 * Bu projede Türkçe kelime listeleri defalarca sessizce öldü. Karar, söz-edimi
 * ekseniyle aynı yöntemle veriliyor: e5 prototip eşleştirmesi, sınıf skoru o
 * sınıfın EN İYİ örneğine benzerlik.
 *
 * ŞÜPHEDE HIZLI YOL: karar verilemezse `stable_knowledge` kabul edilir. Sebep
 * kullanıcının kendi önceliği — "en hızlı ve en doğru yolu kullanmalıyız" — ve
 * uydurma riski ayrıca grounding kapılarıyla korunuyor.
 */
export const knowledgeRecencyValues = [
  /** Model kendi bilgisiyle yazabilir: kalıcı, genel, ansiklopedik. */
  "stable_knowledge",
  /** Canlı kaynak şart: güncel, değişken, tarihli, sayısal. */
  "current_facts",
] as const;

export type KnowledgeRecency = (typeof knowledgeRecencyValues)[number];

export type KnowledgeRecencyDecision = {
  recency: KnowledgeRecency;
  score: number;
  margin: number;
};

const RECENCY_EXEMPLARS: Record<KnowledgeRecency, string[]> = {
  stable_knowledge: [
    "kediler hakkında bir rapor hazırla",
    "fotosentez nasıl çalışır anlat",
    "osmanlı devletinin kuruluşu hakkında yazı",
    "iyi bir özgeçmiş nasıl yazılır",
    "çocuklar için uyku düzeni önerileri",
    "python'da liste ve sözlük farkı",
    "iş görüşmesinde sorulan klasik sorular",
    "akdeniz mutfağının temel özellikleri",
    "bir dilekçe nasıl yazılır",
    "write a report about cats",
    "explain how photosynthesis works",
    "tips for better sleep",
  ],
  current_facts: [
    "bugünkü dolar kuru",
    "2026 enflasyon rakamları hakkında rapor",
    "son çeyrek satış verileri",
    "bu haftaki maç sonuçları",
    "güncel bitcoin fiyatı",
    "dünkü deprem haberleri",
    "şu anki hava durumu",
    "en son çıkan iphone modelinin özellikleri",
    "geçen ay açıklanan işsizlik oranı",
    "bu yılki asgari ücret zammı",
    "today's exchange rate",
    "latest news about the election",
  ],
};

const EXEMPLAR_INDEX: Array<{ recency: KnowledgeRecency; text: string }> = (
  Object.entries(RECENCY_EXEMPLARS) as Array<[KnowledgeRecency, string[]]>
).flatMap(([recency, texts]) => texts.map((text) => ({ recency, text })));

let exemplarVectors: number[][] | null = null;
let exemplarWarmup: Promise<number[][] | null> | null = null;

function dot(a: number[], b: number[]): number {
  let total = 0;
  const length = Math.min(a.length, b.length);
  for (let index = 0; index < length; index += 1) total += a[index] * b[index];
  return total;
}

async function ensureExemplarVectors(
  timeoutMs?: number,
): Promise<number[][] | null> {
  if (exemplarVectors) return exemplarVectors;
  if (!exemplarWarmup) {
    exemplarWarmup = embedTextsForStorage(
      EXEMPLAR_INDEX.map((item) => item.text),
      undefined,
      "understanding-knowledge-recency-v1",
      timeoutMs,
    )
      .then((vectors) => {
        if (vectors && vectors.length === EXEMPLAR_INDEX.length) {
          exemplarVectors = vectors;
          return vectors;
        }
        exemplarWarmup = null;
        return null;
      })
      .catch(() => {
        exemplarWarmup = null;
        return null;
      });
  }
  return exemplarWarmup;
}

/** Test/ölçüm yardımcısı. */
export function resetKnowledgeRecencyVectorsForTests(): void {
  exemplarVectors = null;
  exemplarWarmup = null;
}

export async function classifyKnowledgeRecency(
  text: string,
  options: { timeoutMs?: number } = {},
): Promise<KnowledgeRecencyDecision | null> {
  const trimmed = String(text ?? "").replace(/\s+/g, " ").trim();
  if (!trimmed) return null;

  const [vectors, query] = await Promise.all([
    ensureExemplarVectors(options.timeoutMs),
    embedQueryForStorage(trimmed, undefined, undefined, options.timeoutMs),
  ]).catch(() => [null, null] as const);
  if (!vectors || !query) return null;

  const best = new Map<KnowledgeRecency, number>();
  for (let index = 0; index < EXEMPLAR_INDEX.length; index += 1) {
    const { recency } = EXEMPLAR_INDEX[index];
    const score = dot(query, vectors[index]);
    if (score > (best.get(recency) ?? Number.NEGATIVE_INFINITY)) {
      best.set(recency, score);
    }
  }
  const ranked = [...best.entries()].sort((a, b) => b[1] - a[1]);
  if (ranked.length === 0) return null;
  const [topRecency, topScore] = ranked[0];
  return {
    recency: topRecency,
    score: topScore,
    margin: topScore - (ranked[1]?.[1] ?? 0),
  };
}

/**
 * Karar verilemediğinde HIZLI yol. Araştırma pahalı ve kırılgan; modelin
 * bildiği bir konuda gereksiz araştırma kullanıcıyı bekletiyor.
 */
export function needsLiveResearch(
  decision: KnowledgeRecencyDecision | null | undefined,
): boolean {
  return decision?.recency === "current_facts";
}
