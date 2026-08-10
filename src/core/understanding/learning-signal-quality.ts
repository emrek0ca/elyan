import type { LearningSignal } from "./types.js";

/**
 * Öğrenme sinyali tasarımının tek kuralı.
 *
 * KURAL
 * -----
 * Sürekli öğrenme boru hattı yinelenenleri `(type, key, value, source)`
 * dörtlüsüyle eler — **metadata kimliğe DAHİL DEĞİL**. Sonuç: bir sinyalin
 * öğretici olabilmesi için bilgiyi `value` taşımak zorundadır. Metadata'ya
 * konan zengin bağlam ilk yazımdan sonra "duplicate" diye çöpe gider.
 *
 * ÖLÇÜLEN BEDEL (canlı, 2026-08-10 backfill'i)
 * -------------------------------------------
 * 44.415 olayın 40.678'i (%91,6) yinelenen çıktı. Sebep, değeri anahtarın
 * zaten ima ettiği sayaç-sinyalleri:
 *   task_completed  1.642 satır → 1 farklı değer  (value: "completed")
 *   routing_mode    3.693 satır → 2 farklı değer
 *   task_target     3.693 satır → 2 farklı değer
 * Gerçekten bilgi taşıyan yalnız iki anahtar vardı: `response_scored`
 * (1.330/1.051) ve `message_keywords` (116/109).
 *
 * İKİ AYRI ZARAR
 * --------------
 * 1. Eğitim korpusu: sayaçlar 2-3 satıra çöküyor, öğretecek bir şey yok.
 * 2. Bağlam penceresi: context-builder kullanıcının SON 40 olayını okuyor;
 *    sayaçlar o 40 slotu doldurup bilgi taşıyan sinyalleri dışarı itiyor.
 */

/** Bir parçanın değere katkısı — uzun serbest metin değeri şişirmesin. */
const MAX_PART_LENGTH = 48;
const MAX_VALUE_LENGTH = 200;

function normalizePart(part: unknown): string {
  return String(part ?? "")
    .trim()
    .toLocaleLowerCase("en-US")
    .replace(/\s+/g, " ")
    .slice(0, MAX_PART_LENGTH);
}

/**
 * DURUMU tanımlayan bir değer üretir.
 *
 * Granülerlik bilinçli olarak "durum", "örnek" değil: aynı zincirde aynı
 * gerekçeyle iki kez başarısız olmak AYNI derstir ve tek satıra çökmelidir.
 * Değere görev kimliği gibi benzersiz alanlar konmaz — o zaman hiçbir şey
 * elenmez ve korpus gürültüyle dolar.
 */
export function composeSituationValue(parts: unknown[]): string {
  const cleaned = parts.map(normalizePart).filter(Boolean);
  if (cleaned.length === 0) return "";
  return cleaned.join("|").slice(0, MAX_VALUE_LENGTH);
}

/**
 * Sayısal büyüklükleri kovaya indirger.
 *
 * Ham sayı (3, 4, 5 adım) her seferinde yeni bir satır üretir ve korpusu
 * anlamsızca şişirir; kova ("3-5 adım") gerçek örüntüyü korur.
 */
export function bucketCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0";
  if (value === 1) return "1";
  if (value <= 2) return "2";
  if (value <= 5) return "3-5";
  if (value <= 10) return "6-10";
  return "10+";
}

/**
 * Telemetri biçimli sinyali eğitim korpusunun dışında tutar.
 *
 * Sinyal SİLİNMEZ: bağlam ve gösterge panelleri onu okumayı sürdürür.
 * Yalnız "bundan öğrenilecek bir şey yok" diye işaretlenir — boru hattı
 * `metadata.trainingEligible === false` olanı zaten eliyor.
 */
export function markTelemetryOnly(signal: LearningSignal): LearningSignal {
  return {
    ...signal,
    metadata: {
      ...(signal.metadata ?? {}),
      trainingEligible: false,
      telemetryOnly: true,
    },
  };
}

/**
 * Değeri anahtarın zaten ima ettiği sinyalleri yakalar.
 *
 * Saf ve testlenebilir: yeni bir sinyal eklenirken "bu sayaç mı?" sorusunu
 * gözle değil kuralla yanıtlamak için.
 */
export function isCounterShapedSignal(key: string, value: string): boolean {
  const normalizedKey = normalizePart(key);
  const normalizedValue = normalizePart(value);
  if (!normalizedValue) return true;
  // "task_completed" → "completed": değer anahtarın son parçasını tekrar ediyor.
  if (normalizedKey.endsWith(`_${normalizedValue}`)) return true;
  if (normalizedKey === normalizedValue) return true;
  // Tek parçalı, bileşik olmayan boolean benzeri değerler.
  return ["true", "false", "yes", "no", "ok", "done"].includes(normalizedValue);
}
