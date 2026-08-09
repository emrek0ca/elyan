import type { FastifyBaseLogger } from "fastify";
import {
  embedQueryForStorage,
  embedTextsForStorage,
} from "../brain/semantic-embedder.js";
import {
  getDesktopCapabilityOntology,
  matchDesktopCapabilitiesSemantically,
  type DesktopCapabilityOntologyEntry,
  type DesktopCapabilitySemanticMatch,
  type DesktopCapabilitySideEffectClass,
} from "./desktop-capability-ontology.js";

/**
 * Yetenek eşleştirmesinin GERÇEK anlamsal katmanı.
 *
 * Sözcüksel eşleştirici (karakter n-gramı + IDF) eşanlamlıyı köprüleyemez.
 * Ölçüm bunu net gösterdi: sözlükte geçen ifadelerde %97, hiç görülmemiş
 * ifadelerde %49. Aradaki fark tam olarak eşanlamlılık — "şarj" ile "pil",
 * "ajanda" ile "takvim", "döküman" ile "belge" arasındaki mesafe. Bu mesafe
 * cümle ekleyerek kapanmaz; her yeni cümle bir sonraki eşanlamlıyı açıkta
 * bırakır.
 *
 * Burada backend'de zaten çalışan `multilingual-e5-small` (384 boyut,
 * semantic compute worker arkasında) kullanılıyor. Model erişilemezse
 * sözcüksel skor tek başına döner — yönlendirme asla durmaz, yalnız
 * körleşir.
 */

const CAPABILITY_CACHE_SCOPE = "desktop_capability_ontology_v2";
const WARMUP_TIMEOUT_MS = 20_000;
const QUERY_TIMEOUT_MS = 2_500;

// Karışım ağırlığı. Anlamsal skor eşanlamlıyı yakalar; sözcüksel skor tam
// eşleşmede (özel ad, dosya uzantısı, komut adı) keskindir.
//
// UYARI — ham skorları harmanlamak çalışmaz: e5 kosinüsleri [0.83, 0.91]
// gibi dar bir bantta toplanır, sözcüksel skor ise [0.10, 0.26] bandına
// yayılır. Ham hâlde 0.65/0.35 ağırlık verilse bile ADAYLAR ARASINDAKİ
// FARK sözcüksel tarafta daha büyük olduğu için sıralamayı o belirler:
// ölçümde "şarjı ne alemde" sorgusu bu yüzden clipboard_read'e düşüyordu,
// e5 doğru cevabı (sys_info) ilk sırada bulmuş olmasına rağmen.
//
// Bu yüzden iki skor da adaylar içinde min-max normalize edilir; ancak o
// zaman ağırlıklar söyledikleri şeyi yapar.
//
// Ağırlık ve ceza TAHMİNLE değil, yönlendirme korpusuna karşı süpürülerek
// seçildi (0.30–0.90 × ceza 0–8). Seçilen nokta: tutulan kümede %73.2,
// ana korpusta %97.0, kritik ihlal 4. Daha yüksek anlamsal ağırlık tutulan
// kümeyi düşürüyor (e5 "aç/kapat" kutupluluğunu bulanıklaştırıyor), daha
// düşüğü ise eşanlamlı köprüsünü kaybediyor.
const EMBEDDING_WEIGHT = 0.7;
const LEXICAL_WEIGHT = 1 - EMBEDDING_WEIGHT;

// Karşı-örnek cezası, karşı-örnek ile YALNIZ kullanıcı-dili örnekleri
// arasındaki marj üzerinden hesaplanır. Uzun kimlik metnini (açıklama+usage)
// dahil etmek cezayı tümüyle etkisiz bırakıyordu: e5 uzun alan-içi metne her
// sorguda yüksek benzerlik verdiği için karşı-örnek asla öne geçemiyordu.
// Marj küçük bir sayı olduğundan katsayı büyük; süpürmede 8 en iyi çıktı.
const NEGATIVE_MARGIN_WEIGHT = 8;
// Kimlik metni zayıflatılır: kısa kullanıcı cümleleri kısa karşı-örneklerle
// aynı ölçekte yarışsın diye.
const IDENTITY_DAMPENING = 0.85;

function normalizeScores(values: number[]): number[] {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  for (const value of values) {
    if (value < min) min = value;
    if (value > max) max = value;
  }
  const span = max - min;
  if (!Number.isFinite(span) || span <= 1e-9) {
    return values.map(() => 0);
  }
  return values.map((value) => (value - min) / span);
}

type CapabilityVectors = {
  capability: string;
  positives: number[][];
  negatives: number[][];
  entry: DesktopCapabilityOntologyEntry;
};

let warmupPromise: Promise<CapabilityVectors[] | null> | null = null;
let capabilityVectors: CapabilityVectors[] | null = null;

function positiveTextsFor(entry: DesktopCapabilityOntologyEntry): string[] {
  const manifest = entry.manifest;
  const identity = [manifest.displayName, manifest.description, manifest.usage]
    .filter((part) => part && part.trim().length > 0)
    .join(". ");
  return [identity, ...manifest.utterances.slice(0, 6)].filter(
    (text) => text.trim().length > 0,
  );
}

function negativeTextsFor(entry: DesktopCapabilityOntologyEntry): string[] {
  return entry.manifest.notFor.slice(0, 4).filter((text) => text.trim().length > 0);
}

function dot(left: number[], right: number[]): number {
  let sum = 0;
  for (let index = 0; index < left.length; index += 1) {
    sum += left[index] * right[index];
  }
  return sum;
}

/**
 * Yetenek vektörlerini bir kez hesaplar ve süreç içinde tutar.
 *
 * ~490 kısa metin: ilk çağrıda birkaç saniye sürer, sonrasında bedava.
 * İstek yolunda beklememek için çağıranlar `null` görünce sözcüksel skora
 * düşer; ısınma arka planda tamamlanır ve sonraki istekler tam skoru alır.
 */
export function warmDesktopCapabilityVectors(
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
): Promise<CapabilityVectors[] | null> {
  if (capabilityVectors) return Promise.resolve(capabilityVectors);
  warmupPromise ??= (async () => {
    const ontology = getDesktopCapabilityOntology();
    const texts: string[] = [];
    const layout: Array<{
      entry: DesktopCapabilityOntologyEntry;
      positiveCount: number;
      negativeCount: number;
    }> = [];
    for (const entry of ontology) {
      const positives = positiveTextsFor(entry);
      const negatives = negativeTextsFor(entry);
      texts.push(...positives, ...negatives);
      layout.push({
        entry,
        positiveCount: positives.length,
        negativeCount: negatives.length,
      });
    }
    const vectors = await embedTextsForStorage(
      texts,
      logger,
      CAPABILITY_CACHE_SCOPE,
      WARMUP_TIMEOUT_MS,
    );
    if (!vectors) {
      // Isınma başarısız: bir dahaki çağrı yeniden denesin.
      warmupPromise = null;
      return null;
    }
    const built: CapabilityVectors[] = [];
    let cursor = 0;
    for (const slot of layout) {
      const positives = vectors.slice(cursor, cursor + slot.positiveCount);
      cursor += slot.positiveCount;
      const negatives = vectors.slice(cursor, cursor + slot.negativeCount);
      cursor += slot.negativeCount;
      built.push({
        capability: slot.entry.canonicalId,
        positives,
        negatives,
        entry: slot.entry,
      });
    }
    capabilityVectors = built;
    return built;
  })();
  return warmupPromise;
}

export function isDesktopCapabilityVectorCacheReady(): boolean {
  return capabilityVectors !== null;
}

export function resetDesktopCapabilityVectorsForTests(): void {
  capabilityVectors = null;
  warmupPromise = null;
}

/**
 * Sözcüksel ve anlamsal skoru birleştirerek yetenekleri sıralar.
 *
 * Embedder yoksa saf sözcüksel sonuç döner — çağıran ayrıca bir şey yapmaz.
 */
export async function matchDesktopCapabilitiesWithEmbeddings(input: {
  query: string;
  hints?: string[];
  intent?: string | null;
  sideEffectLevel?: DesktopCapabilitySideEffectClass | null;
  limit?: number;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<DesktopCapabilitySemanticMatch[]> {
  const lexical = matchDesktopCapabilitiesSemantically({
    query: input.query,
    hints: input.hints,
    intent: input.intent,
    sideEffectLevel: input.sideEffectLevel,
    limit: 128,
    threshold: 0,
  });
  const lexicalByCapability = new Map(
    lexical.map((match) => [match.capability, match.score]),
  );

  const vectors = capabilityVectors ?? (await warmDesktopCapabilityVectors(input.logger));
  if (!vectors) return lexical.slice(0, input.limit ?? 8);

  const queryVector = await embedQueryForStorage(
    [input.query, ...(input.hints ?? [])].join(" "),
    input.logger,
    CAPABILITY_CACHE_SCOPE,
    QUERY_TIMEOUT_MS,
  );
  if (!queryVector) return lexical.slice(0, input.limit ?? 8);

  const semantic = vectors.map((candidate) => {
    // positives[0] kimlik metni, kalanı kullanıcı-dili örnekleri.
    const identity = candidate.positives.length > 0 ? dot(queryVector, candidate.positives[0]) : 0;
    let utterance = 0;
    for (const vector of candidate.positives.slice(1)) {
      const score = dot(queryVector, vector);
      if (score > utterance) utterance = score;
    }
    const positive = Math.max(identity * IDENTITY_DAMPENING, utterance);
    let negative = 0;
    for (const vector of candidate.negatives) {
      const score = dot(queryVector, vector);
      if (score > negative) negative = score;
    }
    // Ceza yalnız karşı-örnek gerçekten öndeyken devreye girer: "git nedir"
    // sorgusu git_status'un olumlu örneklerine de benzer, ama karşı-örneğine
    // DAHA ÇOK benzer. Karşılaştırma kullanıcı-dili örnekleriyle yapılır.
    const reference = candidate.positives.length > 1 ? utterance : positive;
    return { candidate, positive, margin: Math.max(0, negative - reference) };
  });

  const normalizedSemantic = normalizeScores(semantic.map((item) => item.positive));
  const normalizedLexical = normalizeScores(
    semantic.map((item) => lexicalByCapability.get(item.candidate.capability) ?? 0),
  );

  const blended = semantic.map((item, index) => {
    const combined =
      EMBEDDING_WEIGHT * normalizedSemantic[index] +
      LEXICAL_WEIGHT * normalizedLexical[index] -
      NEGATIVE_MARGIN_WEIGHT * item.margin;
    return {
      capability: item.candidate.capability,
      score: Number(Math.max(0, combined).toFixed(4)),
      entry: item.candidate.entry,
    };
  });

  blended.sort(
    (left, right) =>
      right.score - left.score ||
      left.capability.localeCompare(right.capability),
  );
  return blended.slice(0, input.limit ?? 8);
}

/** Anlamsal sıralamanın ipucu listesine yansıması için gereken güven eşiği. */
const HINT_CONFIDENCE = 0.55;

/**
 * Planlayıcıya giden yetenek İPUCU listesini anlamsal sıralamayla düzeltir.
 *
 * `requiredCapabilities` bir beyaz liste değil, tercih sırasıdır (güvenlik
 * kapıları — yasaklı liste, otonomi zarfı, gizlilik ve masaüstü onayı —
 * ayrıca ve değişmeden uygulanır). Bu yüzden burada hem yeniden sıralamak
 * hem eksik olan doğru adayı eklemek güvenlidir.
 *
 * Neden gerekli: sezgisel katman "Chrome'u kapat" turunda "Chrome" kelimesini
 * görüp tarayıcı işi sanmış ve close_app'i hiç önermemişti. Planlayıcı yine
 * de manifestten seçebiliyor, ama yanlış sıralanmış bir ipucu onu yanlış
 * yöne itiyor.
 *
 * Embedder yoksa liste OLDUĞU GİBİ döner — yönlendirme asla durmaz.
 */
export async function refineDesktopCapabilityHints(input: {
  query: string;
  capabilities: string[];
  intent?: string | null;
  sideEffectLevel?: DesktopCapabilitySideEffectClass | null;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<string[]> {
  const current = input.capabilities
    .map((capability) => String(capability ?? "").trim())
    .filter(Boolean);
  if (!isDesktopCapabilityVectorCacheReady() && !(await warmDesktopCapabilityVectors(input.logger))) {
    return current;
  }
  const ranked = await matchDesktopCapabilitiesWithEmbeddings({
    query: input.query,
    intent: input.intent,
    sideEffectLevel: input.sideEffectLevel,
    limit: 6,
    logger: input.logger,
  });
  if (ranked.length === 0) return current;

  const existing = new Set(current);
  const rankOf = new Map(ranked.map((match, index) => [match.capability, index]));
  const reordered = [...current].sort((left, right) => {
    const leftRank = rankOf.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightRank = rankOf.get(right) ?? Number.MAX_SAFE_INTEGER;
    return leftRank - rightRank;
  });

  // Yeterince güvenli bir eşleşme listede hiç yoksa başa eklenir. Yetki
  // genişlemez: manifest zaten izinli, kapılar ayrı çalışıyor.
  const best = ranked[0];
  if (best && best.score >= HINT_CONFIDENCE && !existing.has(best.capability)) {
    return [best.capability, ...reordered].slice(0, 16);
  }
  return reordered;
}
