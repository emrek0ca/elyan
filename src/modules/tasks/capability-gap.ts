import type { FastifyBaseLogger } from "fastify";
import {
  isDesktopCapabilityVectorCacheReady,
  matchDesktopCapabilitiesWithEmbeddings,
} from "./desktop-capability-embedding-match.js";

/**
 * YETENEK BOŞLUĞU DEDEKTÖRÜ — "bunu henüz yapamıyorum" diyebilme yeteneği.
 *
 * ÖLÇÜLEN ARIZA (2026-08-23, görev d83da1f2). Kullanıcı "o klasörü sil geri"
 * dedi. Masaüstünde SİLME YETENEĞİ YOKTU. Sistem "yapamıyorum" DEMEDİ:
 * anlamsal eşleştirici "sil" içeren en yakın şeyi seçti ve `delete_memory`
 * çıktı. Yani kullanıcının dosyasını silmek yerine HAFIZASINI silmeye
 * kalkıştı. Apaçık "poke klasörünü sil" bile aynı yere gidiyordu.
 *
 * Kök sebep bir eşik değil, bir EKSİK: sıralayıcı her zaman bir birinci
 * döndürür. "Hiçbiri uymuyor" onun sözlüğünde yok. Boşluk kavramı sistemde
 * hiç temsil edilmediği için, yetenek eksikliği sessizce YANLIŞ ARACA
 * dönüşüyordu.
 *
 * Sessiz yanlış araç, dürüst reddedişten çok daha pahalıdır:
 *   · kullanıcı ne olduğunu anlamaz (hafızası silinmiştir, dosyası durur),
 *   · geri alma yolu yoktur,
 *   · ve eksik yetenek bize HİÇ raporlanmaz — kullanıcı duvara toslar,
 *     biz yıllarca fark etmeyiz.
 *
 * Bu modül iki sinyale bakar ve ikisi de KALİBRASYONSUZ çalışır:
 *
 *   1. KARŞI-ÖRNEK ÜSTÜNLÜĞÜ (yapısal, eşiksiz).
 *      Her yetenek kendi "bunun için KULLANMA" örneklerini beyan eder
 *      (`notFor` + `whenNotToUse`). Sorgu bu örneklere, yeteneğin kendi
 *      kullanıcı-dili örneklerinden DAHA ÇOK benziyorsa, yeteneğin kendi
 *      beyanı "ben bu iş için değilim" diyor demektir. Bunu görmezden gelip
 *      yürütmek, sözleşmeyi okuyup tersini yapmaktır.
 *
 *   2. ZAYIF KANIT (ham skor, normalize edilmemiş).
 *      `score` alanı adaylar içinde min-max normalize edilir; top-1 yapısı
 *      gereği hep yüksektir (ölçümde 0.70–1.00). O yüzden "yapılabilir mi"
 *      sorusunu CEVAPLAYAMAZ. Ham e5 kosinüsü ise dar ama gerçek bir bantta
 *      durur; taban ondan okunur.
 *
 * TASARIM KARARI — hangi hata ucuz?
 *   Yanlış YAPMAK canlıda zarar verir; yanlış REDDETMEK yalnız can sıkar ve
 *   üstelik kendini rapor eder (aşağıdaki defter). Bu yüzden şüphede
 *   reddediyoruz. Ama eşik gereksiz yere gevşek de değil: karşı-örnek
 *   sinyali yapısaldır, ham taban ise ölçülene kadar BİLİNÇLİ olarak düşük
 *   tutuldu — kapı önce yalnız apaçık vakalarda konuşsun.
 */

export type CapabilityGapReason =
  | "capability_fits"
  | "counter_example_dominates"
  | "weak_evidence"
  | "no_candidate"
  | "semantics_unavailable";

export type CapabilityGapVerdict = {
  /** true → bu istek mevcut yetenek uzayında karşılanamıyor. */
  gap: boolean;
  /** Boşluk yoksa seçilecek yetenek; varsa "en yakın ama uymayan". */
  capability: string | null;
  reason: CapabilityGapReason;
  /** Ham anlamsal kanıt (normalize edilmemiş). */
  positive: number;
  /** Karşı-örnek üstünlüğü; > 0 ise yeteneğin kendi beyanı itiraz ediyor. */
  counterEvidence: number;
  /** Kullanıcıya söylenecek dürüst cümle; boşluk yoksa boş dize. */
  message: string;
};

/**
 * Karşı-örnek üstünlüğü eşiği.
 *
 * Sıfırın hemen üstü gürültüdür: bir sorgu karşı-örneğe kıl payı daha çok
 * benzeyebilir. Eşik, farkın ANLAMLI olmasını ister. Eşleştiricinin kendi
 * ceza ağırlığıyla aynı büyüklük mertebesinde tutuldu.
 */
const COUNTER_EVIDENCE_FLOOR = 0.03;

/**
 * Ham kanıt tabanı.
 *
 * multilingual-e5 kosinüsleri dar bir bantta toplanır; ilgisiz bir çift bile
 * 0.70'in altına pek inmez. Taban BİLİNÇLİ olarak düşük: kapı önce yalnız
 * "hiçbir şeye benzemiyor" vakalarında konuşsun, ölçüm geldikçe yükseltilsin.
 * Yükseltmeden önce `eval:local-execution` koşulmalı — bu sayı doğrudan
 * KAÇIRMA oranını belirler.
 */
const POSITIVE_EVIDENCE_FLOOR = 0.7;

/**
 * ZORLAMA KİPİ — VARSAYILAN KAPALI.
 *
 * Kapı açıkken yanlış kalibre bir taban GEÇERLİ komutları da reddeder; bu
 * projede "tahmin sert sözleşmeye dönüşüyor" hata sınıfı üç kez tekrarlandı.
 * Bu yüzden dedektör önce GÖZLEMCİ olarak çalışır: boşlukları defterine
 * yazar, log'a düşer, davranışı DEĞİŞTİRMEZ.
 *
 * Açmadan önce koşulacak ölçüm: `npm run eval:local-execution`. Beklenen
 * kabul ölçütü — YANLIŞ YÜRÜTME 0 kalmalı, kaçırma artışı taban 84.6'nın
 * altına indirmemeli. Ham skor dağılımı ölçülmeden `POSITIVE_EVIDENCE_FLOOR`
 * asla yükseltilmemeli.
 */
export const CAPABILITY_GAP_ENFORCED =
  String(process.env.ELYAN_CAPABILITY_GAP_ENFORCED ?? "").trim().toLowerCase() === "true";

const GAP_MESSAGE =
  "Bunu henüz yapamıyorum — elimdeki araçların hiçbiri bu işi karşılamıyor. " +
  "Yanlış bir aracı deneyip beklemediğin bir şey yapmaktansa söylemeyi tercih ederim.";

export type CapabilityGapRecord = {
  query: string;
  nearestCapability: string | null;
  reason: CapabilityGapReason;
  positive: number;
  counterEvidence: number;
  at: string;
};

/**
 * Boşluk defteri.
 *
 * Dürüst reddedişin ikinci faydası: eksik yetenek artık KAYIT altına giriyor.
 * Sessiz yanlış araç seçiminde bu bilgi hiç oluşmuyordu — kullanıcı duvara
 * tosluyor, biz haberdar olmuyorduk. Bellekte tutulur ve rapor edilir;
 * kalıcılık gerekince buradan bir tabloya bağlanır.
 */
const gapLedger: CapabilityGapRecord[] = [];
const GAP_LEDGER_LIMIT = 500;

export function recordedCapabilityGaps(): readonly CapabilityGapRecord[] {
  return gapLedger;
}

export function clearRecordedCapabilityGapsForTests(): void {
  gapLedger.length = 0;
}

/** En çok istenen ama karşılanamayan işler — yetenek yol haritası girdisi. */
export function capabilityGapReport(): Array<{
  nearestCapability: string;
  count: number;
  samples: string[];
}> {
  const grouped = new Map<string, CapabilityGapRecord[]>();
  for (const record of gapLedger) {
    const key = record.nearestCapability ?? "(aday yok)";
    const bucket = grouped.get(key);
    if (bucket) bucket.push(record);
    else grouped.set(key, [record]);
  }
  return [...grouped.entries()]
    .map(([nearestCapability, records]) => ({
      nearestCapability,
      count: records.length,
      samples: records.slice(-3).map((record) => record.query),
    }))
    .sort((left, right) => right.count - left.count);
}

function remember(record: CapabilityGapRecord): void {
  gapLedger.push(record);
  if (gapLedger.length > GAP_LEDGER_LIMIT) {
    gapLedger.splice(0, gapLedger.length - GAP_LEDGER_LIMIT);
  }
}

/**
 * SAF YARGI — ek gömme çağrısı YOK.
 *
 * Sıcak yolda (yerel yürütme kararı) eşleştirici zaten koşuyor; boşluk için
 * ikinci bir e5 turu açmak bu projede özellikle pahalı: gecikme bütçesi
 * ölçülüyor ve yönlendirme yolu model ısınmasına asla takılmamalı. Bu yüzden
 * karar, ELDEKİ kanıttan verilir; `detectCapabilityGap` yalnız kanıtı olmayan
 * çağrılar için eşleştiriciyi kendisi koşar.
 */
export function judgeCapabilityEvidence(input: {
  capability: string | null;
  /** Ham anlamsal skor; ölçülmediyse `undefined` (sıfır DEĞİL). */
  positive?: number;
  counterEvidence?: number;
  query?: string;
}): CapabilityGapVerdict {
  const capability = input.capability ?? null;
  const positive = input.positive ?? 0;
  const counterEvidence = input.counterEvidence ?? 0;
  const hasRawEvidence = input.positive !== undefined;

  let reason: CapabilityGapReason = "capability_fits";
  if (!capability) {
    reason = "no_candidate";
  } else if (counterEvidence > COUNTER_EVIDENCE_FLOOR) {
    reason = "counter_example_dominates";
  } else if (hasRawEvidence && positive < POSITIVE_EVIDENCE_FLOOR) {
    reason = "weak_evidence";
  }

  const gap = reason !== "capability_fits";
  if (gap) {
    remember({
      query: String(input.query ?? ""),
      nearestCapability: capability,
      reason,
      positive,
      counterEvidence,
      at: new Date().toISOString(),
    });
  }
  return {
    gap,
    capability,
    reason,
    positive,
    counterEvidence,
    message: gap ? GAP_MESSAGE : "",
  };
}

/**
 * "Bu istek mevcut yetenek uzayında gerçekten karşılanıyor mu?"
 *
 * Eşleştiriciyi kendisi koşar; sıcak yolda `judgeCapabilityEvidence` tercih
 * edilmeli. Vektörler hazır değilse `semantics_unavailable` döner ve boşluk
 * İDDİA ETMEZ: kapının körken konuşması, sistemin yapabildiği işleri
 * reddetmesi demek olurdu. Şüphede eski davranış sürer.
 */
export async function detectCapabilityGap(input: {
  query: string;
  /** Verilirse yalnız bu yetenek yargılanır (planın seçtiği adım). */
  capability?: string | null;
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">;
}): Promise<CapabilityGapVerdict> {
  const query = String(input.query ?? "").trim();
  const unavailable: CapabilityGapVerdict = {
    gap: false,
    capability: null,
    reason: "semantics_unavailable",
    positive: 0,
    counterEvidence: 0,
    message: "",
  };
  if (!query) return unavailable;
  if (!isDesktopCapabilityVectorCacheReady()) return unavailable;

  const ranked = await matchDesktopCapabilitiesWithEmbeddings({
    query,
    limit: 8,
    logger: input.logger,
  });
  const requested = String(input.capability ?? "").trim();
  const best = requested
    ? ranked.find((match) => match.capability === requested)
    : ranked[0];

  if (!best) {
    // İstenen yetenek sıralamada hiç görünmüyorsa yargılayacak kanıt yok:
    // boşluk İDDİA ETMİYORUZ, yalnız durumu bildiriyoruz.
    const verdict: CapabilityGapVerdict = {
      gap: !requested,
      capability: null,
      reason: "no_candidate",
      positive: 0,
      counterEvidence: 0,
      message: requested ? "" : GAP_MESSAGE,
    };
    if (verdict.gap) {
      remember({
        query,
        nearestCapability: null,
        reason: verdict.reason,
        positive: 0,
        counterEvidence: 0,
        at: new Date().toISOString(),
      });
    }
    return verdict;
  }

  return judgeCapabilityEvidence({
    capability: best.capability,
    positive: best.positive,
    counterEvidence: best.counterEvidence,
    query,
  });
}
