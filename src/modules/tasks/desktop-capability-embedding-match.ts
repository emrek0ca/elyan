import type { FastifyBaseLogger } from "fastify";
import { normalizeText } from "./desktop-capability-ontology.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
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
  speechActAllowsExecution,
  type SpeechAct,
} from "../../core/understanding/speech-act.js";
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
// This is startup-only and never blocks a request. The previous 20s budget
// was shorter than the single-process ~490-text catalogue on a cold ONNX
// session, so the cache was consistently discarded even after model warmup.
// Keep it bounded, but give the API authority enough time to build it once.
const WARMUP_TIMEOUT_MS = 120_000;
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

/**
 * MUTLAK EŞİK DENENDİ VE ÖLÇÜMLE REDDEDİLDİ (2026-08-22).
 *
 * Normalize edilmiş skor mutlak güven ölçüsü değildir: sorgu hiçbir yeteneğe
 * uymasa bile en iyi aday 1.0'a yakın çıkar. 30 gündelik sohbet cümlesinden
 * ("bugün kendimi yorgun hissediyorum", "sence hayatın anlamı ne") OTUZU da
 * bir yetenekle top-1 eşleşti, birkaçı 1.0000 skorla.
 *
 * Çözüm olarak ham e5 kosinüsünü ("hiçbir yetenek uymuyor" diyebilmek için)
 * eşiklemeyi denedim. Dağılımlar ÇAKIŞIYOR:
 *
 *   nötr sohbet (n=20) : min 0.8274  med 0.8581  max 0.8934
 *   gerçek komut (n=150): min 0.8388  med 0.9421  max 0.9819
 *
 * 0.89 eşiği nötrlerin yalnız 2/20'sini elerken GERÇEK komutların 25/150'sini
 * de eliyordu — üstelik en tipik olanlarını: "Terminali kapat" (0.8869),
 * "chrome'u açar mısın" (0.8885), "Notlar uygulamasını kapat" (0.8899).
 * Ters yönde de ayırmıyor: eval'in "sohbet olmalıydı" dediği "bilgisayarı
 * kapat" 0.9230 ile komutların çoğundan YÜKSEK.
 *
 * Sonuç: "eylem mi sohbet mi" ayrımı yetenek benzerliğinden okunamaz; o karar
 * söz-edimi katmanının işi (`core/understanding/speech-act.ts`) ve orada
 * ölçülen ayrım çok daha keskin. Buraya mutlak eşik EKLEME.
 */
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

/** Bir yeteneğin seçilebilir olması için gereken asgari kullanıcı-dili örneği. */
const MIN_SEMANTIC_PHRASES = 4;

/**
 * YENİ ARAÇ EKLENDİĞİNDE HİSSEDİLMELİ.
 *
 * ÖLÇÜM (2026-08-23): `file_find` yeteneği eklendi, masaüstü onu beyan etti,
 * manifest ve ontolojiye girdi — ama eşleştirmede HİÇ SEÇİLMEDİ (kendi
 * kullanım örnekleriyle bile 0/4). Sebep: bu fonksiyon yalnız
 * `manifest.utterances` okuyordu; yeni yeteneğin `utterances`ı boştu
 * (yazarı `whenToUse` doldurmuştu) ve o yüzden anlamsal varlığı SIFIRDI.
 *
 * Yani bir araç eklemek, onu seçilebilir yapmıyordu. Kullanıcının "araçları
 * geliştirdikçe gücü hissedilmeli" isteği tam olarak burada kırılıyordu.
 *
 * Artık `whenToUse` de olumlu metinlere giriyor: bir yetenek, kullanım
 * örneklerini nereye yazarsa yazsın seçilebilir olur. `utterances` hâlâ
 * öncelikli (phrasebook özenle yazılmış kullanıcı dilidir); `whenToUse`
 * eksiği kapatır.
 */
function positiveTextsFor(entry: DesktopCapabilityOntologyEntry): string[] {
  const manifest = entry.manifest;
  const identity = [manifest.displayName, manifest.description]
    .filter((part) => part && part.trim().length > 0)
    .join(". ");
  const appUsage = ["close_app", "open_app", "browser_control"].includes(entry.canonicalId)
    ? [manifest.usage]
    : [];
  const utterances = manifest.utterances.slice(0, 6);
  // `whenToUse` TAMAMLAYICIDIR, EK YÜK DEĞİL.
  //
  // İlk sürümde her yeteneğe eklenince katalog 560 → 694 metne çıktı (%24) ve
  // e5 ısınması bütçeyi aştı: ölçüm kapısı "vektör önbelleği hazır değil"
  // diyerek üretim sayısını vermeyi reddetti. Üretimde bu SESSİZCE sözcüksel
  // skora düşmek demekti.
  //
  // Phrasebook'u özenle yazılmış yetenekler ek metne muhtaç değil; eksik olan
  // yeni yetenekler ise seçilebilmek için buna muhtaç. Bu yüzden yalnız
  // asgariyi tamamlar.
  const whenToUse =
    utterances.length >= MIN_SEMANTIC_PHRASES || !Array.isArray(manifest.whenToUse)
      ? []
      : manifest.whenToUse
          .filter((text) => typeof text === "string")
          .slice(0, MIN_SEMANTIC_PHRASES - utterances.length);
  const seen = new Set<string>();
  return [identity, ...appUsage, ...utterances, ...whenToUse].filter((text) => {
    const trimmed = String(text ?? "").trim();
    if (!trimmed || seen.has(trimmed)) return false;
    seen.add(trimmed);
    return true;
  });
}

/**
 * Bir yeteneğin kullanıcı dilinde KAÇ örneği var?
 *
 * Sıfırsa o yetenek pratikte seçilemez: yalnız kimlik metniyle yarışır ve
 * örnek cümlesi olan her rakibe kaybeder. Kapı testi bunu yakalar.
 */
export function capabilityUtteranceCount(
  entry: DesktopCapabilityOntologyEntry,
): number {
  const manifest = entry.manifest;
  const utterances = Array.isArray(manifest.utterances) ? manifest.utterances.length : 0;
  const whenToUse = Array.isArray(manifest.whenToUse) ? manifest.whenToUse.length : 0;
  return utterances + whenToUse;
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
 *
 * EŞİĞİ DÜŞÜRME DENENDİ VE REDDEDİLDİ (2026-08-22). Süpürme (150 komut,
 * 25 sohbet cümlesi, söz edimi kapısı açık):
 *
 *   eşik | komut hızlı yolda | top-1 yanlış | sohbet sızan
 *   0.20 | 102/150 (68.0%)   | 2 (2.0%)     | 0/25
 *   0.18 | 107/150 (71.3%)   | 2 (1.9%)     | 0/25
 *   0.15 | 110/150 (73.3%)   | 3 (2.7%)     | 0/25
 *   0.12 | 112/150 (74.7%)   | 5 (4.5%)     | 0/25
 *   0.10 | 113/150 (75.3%)   | 5 (4.4%)     | 1/25
 *
 * Sayı 0.15'i cazip gösteriyor. Kazanılan 8 isteğe TEK TEK bakınca kazanç
 * sahte: "içine şunu yazdığın basit bir txt bırak" (0.1896) gönderme
 * içeriyor — "şunu" önceki turda; "ekibe bir yazı gönder ama önce göreyim"
 * (0.1749) bir ONAY KISITI taşıyor. Hızlı yol anlama zarfını boşaltır; bu
 * ikisinde kaybedilen şey ipucu kalitesi değil, isteğin kendisi.
 *
 * Yani düşük marj bir kusur değil, doğru sinyal: bağlama muhtaç istekler
 * zaten orada toplanıyor. Gecikme kazancı için ağır yolu kapatmak, tam da
 * bağlamı gereken isteklerde kapatmak demek.
 */
const FAST_PATH_MARGIN = 0.2;

/**
 * Yerel eylem KANITI için gereken ayrışma.
 *
 * Sayısı bugün `FAST_PATH_MARGIN` ile aynı ama AYNI ŞEY DEĞİL ve tek sabit
 * olarak paylaşılamaz: hızlı yol eşiği bir GECİKME ayarıdır (yanılırsa bir
 * tur 2,5 sn yavaşlar), bu eşik bir GÜVENLİK kapısıdır (yanılırsa kullanıcının
 * makinesinde yanlış iş çalışır). Tek sabit paylaşıldığında, ileride gecikme
 * için yapılan bir ayar yürütme kapısını sessizce gevşetir.
 *
 * Ayrı ayrı ölçülür, ayrı ayrı değiştirilir.
 */
const LOCAL_ACTION_MARGIN = 0.2;

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

/**
 * YEREL EYLEM YETENEKLERİ — manifestten TÜRETİLİR, elle yazılmaz.
 *
 * Ölçüt: `privacyClass === "permission_gated"` ve `requiresApproval`. Bu, "bu
 * iş kullanıcının makinesinde/hesabında gerçekten bir şey yapar" demenin
 * manifestteki karşılığıdır: uygulama aç/kapat, medya oynat, tarayıcı sür,
 * shell, mail gönder, takvim/hatırlatıcı yaz, WhatsApp, MCP aracı.
 *
 * Belge/grafik üretimi BİLEREK dışarıda: onları sunucu da üretebilir ve
 * masaüstüne zorlamak mevcut davranışı bozardı. `get_weather`, `image_generate`,
 * `web_research` de dışarıda kalır.
 *
 * Elle tutulan `DESKTOP_ONLY_CAPABILITIES` listesi ayrı bir amaca hizmet eder
 * ve olduğu gibi durur; bu küme yalnız YÖNLENDİRME KANITI içindir.
 */
const LOCAL_ACTION_CAPABILITIES: ReadonlySet<string> = new Set(
  DESKTOP_CAPABILITY_MANIFEST.filter(
    (entry) => entry.privacyClass === "permission_gated" && entry.requiresApproval,
  ).map((entry) => entry.name),
);

export function isLocalActionCapability(capability: string): boolean {
  return LOCAL_ACTION_CAPABILITIES.has(String(capability ?? "").trim());
}

export function localActionCapabilityNames(): string[] {
  return [...LOCAL_ACTION_CAPABILITIES].sort();
}

/**
 * "Bu istek, yetenek uzayında tek ve net bir YEREL EYLEME oturuyor mu?"
 *
 * Canlı arıza (2026-08-22): "Müslüm gürsesden bir şeyler çal" sohbete düştü.
 * `play_media` masaüstünde VAR ve eşleştirici onu 1.000 skor / 0.316 marjla
 * birinci sırada veriyordu — ama eşleştirici yalnız rota ZATEN masaüstü
 * seçildikten sonra çalıştırılıyordu (`isDesktopRoute` şartı). Yani karar
 * verecek kanıt sistemde vardı, kimse ona sormuyordu.
 *
 * Marj şartı yanlış-pozitifleri kesiyor: ölçümde "Bana bir şiir yaz" turu
 * top-1 `image_generate` (0.935) ile geliyor ama marjı 0.170 — eşiğin altında,
 * reddedilir. Yerel-eylem şartı da "Bugün hava nasıl" (get_weather, marj
 * 0.695) gibi yüksek marjlı ama sunucunun da yapabildiği işleri eler.
 */
export async function evaluateLocalActionEvidence(input: {
  query: string;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<{
  /** Marj eşiğini de geçen, TEK BAŞINA kullanılabilir güçlü kanıt. */
  localAction: boolean;
  /**
   * Top-1 bir yerel eylem yeteneği mi — MARJDAN BAĞIMSIZ.
   *
   * Ayrı tutuluyor çünkü marj eşiği, konuşma eylemi ekseni devredeyken
   * GEREKSİZ ve ZARARLI: ölçümde ("Serdar ortaçtan bir şeyler çal" marj 0.054)
   * gerçek komutları kesiyordu, oysa tehlikeli sınıfı zaten konuşma eylemi
   * kapatıyor. Uzlaşma kuralı bu alanı kullanır.
   */
  localActionCapability: boolean;
  capability: string | null;
  score: number;
  margin: number;
  reason:
    | "confident_local_action"
    | "not_local_action"
    | "ambiguous_margin"
    | "semantics_unavailable";
}> {
  const empty = {
    localAction: false,
    localActionCapability: false,
    capability: null,
    score: 0,
    margin: 0,
    reason: "semantics_unavailable" as const,
  };
  if (!String(input.query ?? "").trim()) return empty;
  // Vektörler ısınmadıysa BEKLEME: yönlendirme yolu asla model ısıtmasına
  // takılmamalı. Şüphede eski davranış (sunucu) sürer.
  if (!isDesktopCapabilityVectorCacheReady()) return empty;

  const ranked = await matchDesktopCapabilitiesWithEmbeddings({
    query: input.query,
    limit: 2,
    logger: input.logger,
  });
  const best = ranked[0];
  if (!best) return empty;
  const margin = best.score - (ranked[1]?.score ?? 0);
  const localActionCapability = isLocalActionCapability(best.capability);
  const base = {
    capability: best.capability,
    score: best.score,
    margin,
    localActionCapability,
  };
  if (!localActionCapability) {
    return { ...base, localAction: false, reason: "not_local_action" };
  }
  if (margin < LOCAL_ACTION_MARGIN) {
    return { ...base, localAction: false, reason: "ambiguous_margin" };
  }
  return { ...base, localAction: true, reason: "confident_local_action" };
}

export type FastPathDecision = {
  fastPath: boolean;
  capability: string | null;
  score: number;
  margin: number;
  reason:
    | "confident_single_capability"
    | "ambiguous_margin"
    | "orchestration_capability"
    | "speech_act_blocks"
    | "semantics_unavailable";
  /** Söz edimi kapısının bu kararda okunup okunmadığı — sessiz kalmasın. */
  speechAct: SpeechAct | null;
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
  /**
   * Yönlendiricinin ZATEN hesapladığı söz edimi. Burada yeniden hesaplamıyoruz:
   * hızlı yolun tek varlık sebebi gecikmeyi düşürmek, ek bir e5 çağrısı o
   * amacı yer.
   *
   * Verilmezse davranış değişmez (hızlı yol eskisi gibi çalışır). Bilgi yoksa
   * yavaşlatmak da bir bedel; kapı yalnız ELDE VERİ VARKEN konuşur.
   */
  speechAct?: SpeechAct | null;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<FastPathDecision> {
  const speechAct = input.speechAct ?? null;
  const empty: FastPathDecision = {
    fastPath: false,
    capability: null,
    score: 0,
    margin: 0,
    reason: "semantics_unavailable",
    speechAct,
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
  const base = { capability: best.capability, score: best.score, margin, speechAct };

  if (ORCHESTRATION_CAPABILITIES.has(best.capability)) {
    return { ...base, fastPath: false, reason: "orchestration_capability" };
  }
  // SÖZ EDİMİ KAPISI — aynı sinyali `evaluateLocalActionEvidence` okuyordu,
  // burası okumuyordu.
  //
  // Ölçüldü: 25 gündelik sohbet cümlesinin 6'sı bu kapıdan hızlı yola
  // giriyordu — "bugün kendimi yorgun hissediyorum" → get_weather,
  // "bazen susmak konuşmaktan iyi geliyor" → desktop_os.volume,
  // "en sevdiğin film türü hangisi" → desktop_os.active_window. Hızlı yol
  // ağır anlama hattını (~2,5 sn) ve hafıza aramasını ATLAR; yani tam da
  // anlaşılmayı en çok gerektiren cümlede anlama kapatılıyordu.
  //
  // Bu cümleler üretimde `isDesktopRoute` olmadan buraya ULAŞMIYOR — yani
  // arıza gizil, canlı değil. Kapı yine de burada: aynı sinyalin bir kapıda
  // okunup diğerinde okunmaması bu projede tekrar eden hata sınıfı.
  if (speechAct && !speechActAllowsExecution(speechAct)) {
    return { ...base, fastPath: false, reason: "speech_act_blocks" };
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
