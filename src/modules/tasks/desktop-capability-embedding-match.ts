import type { FastifyBaseLogger } from "fastify";
import { normalizeText } from "./desktop-capability-ontology.js";
import {
  actionPolarityAdjustment,
  capabilitySafetyAdjustment,
  resolveQueryActionPolarity,
} from "./capability-action-polarity.js";
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
// seçildi (0.30–0.90 × ceza 0–8). Genel kullanım/politika metnini vektör
// pozitiflerinden çıkarmak, tutulan kümeyi %74.5'e taşıdı; yalnızca uygulama
// aç/kapat ve tarayıcı entity ayrımı için manifest usage'ı koruyoruz. Ağırlık
// 0.7'de tutulur: e5 eşanlamlı köprüsünü korur, sözcüksel katman da eylem
// kutbunu düzeltir.
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
  const identity = [manifest.displayName, manifest.description]
    .filter((part) => part && part.trim().length > 0)
    .join(". ");
  const appUsage = ["close_app", "open_app", "browser_control"].includes(entry.canonicalId)
    ? [manifest.usage]
    : [];
  return [identity, ...appUsage, ...manifest.utterances.slice(0, 6)].filter(
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
  /** Evaluators/startup may opt into warmup; request paths must not wait. */
  allowWarmup?: boolean;
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

  const vectors =
    capabilityVectors ??
    (input.allowWarmup === true
      ? await warmDesktopCapabilityVectors(input.logger)
      : null);
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

  // Eylem kutbu HARMANDAN SONRA uygulanır.
  //
  // Sözcüksel katmanda uygulanan ceza buraya ulaşmıyor: `normalizeScores`
  // adayları min-max normalize ettiği için ceza sıralamayı korusa bile
  // ölçeklenerek eziliyordu. Ölçüldü: sözcüksel katman düzeltildikten SONRA
  // bile tam boru hattında "Chrome'u aç" top-1'de `close_app` veriyordu.
  // Zıt eylem yapısal bir veto; harmanın çıktısına uygulanmalı.
  const queryPolarity = resolveQueryActionPolarity(normalizeText(input.query));
  const blended = semantic.map((item, index) => {
    const combined =
      EMBEDDING_WEIGHT * normalizedSemantic[index] +
      LEXICAL_WEIGHT * normalizedLexical[index] -
      NEGATIVE_MARGIN_WEIGHT * item.margin +
      actionPolarityAdjustment({
        queryPolarity,
        capabilityId: item.candidate.capability,
      }) +
      capabilitySafetyAdjustment({
        normalizedQuery: normalizeText(input.query),
        capabilityId: item.candidate.capability,
      });
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
 * Hızlı yol için gereken AYRIŞMA (top-1 ile top-2 arasındaki fark).
 *
 * Mutlak skora bakmıyoruz, çünkü ölçmüyor: skorlar adaylar içinde min-max
 * normalize edildiği için top-1 yapısı gereği hep yüksek çıkıyor (ölçümde
 * 0.70–1.00 arası, eşik ne olursa olsun aynı kümeyi seçiyor). Bilgi taşıyan
 * şey FARK.
 *
 * Ölçülen ayrışma (canlı eşleştirici):
 *   "Terminali kapat"      0.270   tek ve net
 *   "şu csv'yi analiz et"  0.523   tek ve net
 *   "bunu pdf yap"         0.054   takip isteği — bağlam ŞART
 *   "Atatürk kimdir"       0.011   eylem bile değil
 *   "naber"                0.008   sohbet
 *
 * 0.2 eşiği bu ayrımı temiz yapıyor: korpusta hızlı yola giren 124 istekten
 * 4'ünde top-1 hatalı (%3) ve o hata bile yürütmeyi değiştirmiyor — yalnız
 * planlayıcıya daha zayıf bir ipucu gider, seçim yine tam manifestten yapılır.
 */
const FAST_PATH_MARGIN = 0.2;

/**
 * Hızlı yola ASLA girmeyen yetenekler.
 *
 * Bunlar tek adımlık iş değil, çok adımlı yürütme kabuğu: hedefi kendileri
 * yorumlar, ekranı gözler, sırayla karar verir. Böyle bir istek tam da
 * bağlam anlamaya en çok ihtiyaç duyan istektir; orada 2.5 saniyeyi kesmek
 * tasarruf değil, körleştirmedir.
 */
const ORCHESTRATION_CAPABILITIES = new Set([
  "desktop_operator.run",
  "browser_agent.run",
  "run_skill",
  "mcp_call_tool",
]);

export type FastPathDecision = {
  fastPath: boolean;
  capability: string | null;
  score: number;
  margin: number;
  reason:
    | "confident_single_capability"
    | "ambiguous_margin"
    | "orchestration_capability"
    | "semantics_unavailable";
};

/**
 * "Bu istek tek ve net bir yetenekle karşılanabilir mi?"
 *
 * Ağır anlama hattı (ölçüm: ~2.5 sn) + hafıza araması (~1.3 sn) her masaüstü
 * görevinde koşuyordu. "Terminali kapat" gibi tek eylemlik bir komut için bu
 * bütçe boşa gidiyor ve kullanıcı gecikmeyi hissediyor.
 *
 * Eski kapı bir REGEX'ti: fiil listesi ("aç|kapat|başlat…") ve uygulama adı
 * yakalama. Türkçe eklerde kırılıyordu — "Terminali kapat" isteğinden
 * uygulama adını "Terminali" diye çıkarıyordu. Buradaki karar tamamen
 * anlamsal: aynı e5 tabanlı eşleştirici, kelime listesi yok.
 *
 * Embedder erişilemezse `fastPath: false` döner — yani ŞÜPHEDE AĞIR YOL.
 * Hızlı yolu yanlışlıkla açmak, bir turu yavaşlatmaktan pahalıdır.
 */
export async function evaluateDesktopFastPath(input: {
  query: string;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<FastPathDecision> {
  const empty: FastPathDecision = {
    fastPath: false,
    capability: null,
    score: 0,
    margin: 0,
    reason: "semantics_unavailable",
  };
  if (!String(input.query ?? "").trim()) return empty;
  if (!isDesktopCapabilityVectorCacheReady()) {
    return empty;
  }

  const ranked = await matchDesktopCapabilitiesWithEmbeddings({
    query: input.query,
    limit: 2,
    logger: input.logger,
  });
  const best = ranked[0];
  if (!best) return empty;
  const margin = best.score - (ranked[1]?.score ?? 0);
  const base = { capability: best.capability, score: best.score, margin };

  if (ORCHESTRATION_CAPABILITIES.has(best.capability)) {
    return { ...base, fastPath: false, reason: "orchestration_capability" };
  }
  if (margin < FAST_PATH_MARGIN) {
    return { ...base, fastPath: false, reason: "ambiguous_margin" };
  }
  return { ...base, fastPath: true, reason: "confident_single_capability" };
}

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
  if (!isDesktopCapabilityVectorCacheReady()) {
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
