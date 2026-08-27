/**
 * Tipsiz veriden güvenli okuma — TEK kaynak.
 *
 * NEDEN VAR: bu altı fonksiyon kod tabanında yaklaşık yüz otuz kez yeniden
 * yazılmıştı. `readRecord` elli, `asRecord` on bir ayrı dosyada — ve ikisi
 * AYNI fonksiyondu, yalnız adları farklıydı. Her kopya kendi başına doğruydu;
 * sorun kopyaların varlığı değil, birbirinden bağımsız değişebilmeleriydi.
 *
 * Ölçülen sonuç: `compactText` adı altında beş farklı davranış birikmişti
 * (bkz. `text.ts`). Aynı şey burada da olabilirdi — `readRecord`'ın boş
 * durumu bazı dosyalarda `null`, bazılarında `{}` döndürüyor. İkisi de
 * meşru; ikisinin de AYNI adı taşıması meşru değil. Bu yüzden burada iki ad
 * var ve hangisini istediğini çağıran söyler.
 *
 * Bu modül kasıtlı olarak aptaldır: iş mantığı yok, bağımlılık yok, yan etki
 * yok. Yeni bir soyutlama katmanı değil — var olan kopyaların toplandığı yer.
 */

/** Nesne ise kendisi, değilse `null`. Yokluğu AYIRT ETMEK isteyen çağıran. */
export function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Nesne ise kendisi, değilse boş nesne. Yokluğu ÖNEMSEMEYEN çağıran. */
export function asRecordOrEmpty(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/**
 * Kayıttaki metin alanı. Boş/whitespace metin YOK sayılır (`null`) — çağıranların
 * ezici çoğunluğu bunu bekliyordu ve `""` ile `null` ayrımını zaten yapmıyordu.
 */
export function recordString(
  record: Record<string, unknown> | null | undefined,
  key: string,
): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** Kayıttaki sonlu sayı alanı. `NaN`/`Infinity` sayılmaz. */
export function recordNumber(
  record: Record<string, unknown> | null | undefined,
  key: string,
): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Kayıttaki boolean alanı. `null` = ALAN YOK; `false` = alan var ve false.
 * Bu ayrım korunuyor: birçok kapı "belirtilmemiş" ile "hayır" arasında ayrım
 * yapıyor ve `value === true` kısayolu o ayrımı siler.
 */
export function recordBoolean(
  record: Record<string, unknown> | null | undefined,
  key: string,
): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

/** Kayıttaki dizi alanı; dizi değilse boş dizi. */
export function recordArray(
  record: Record<string, unknown> | null | undefined,
  key: string,
): unknown[] {
  const value = record?.[key];
  return Array.isArray(value) ? value : [];
}

/** Kayıttaki metin dizisi; metin olmayan ve boş öğeler düşer. */
export function recordStringList(
  record: Record<string, unknown> | null | undefined,
  key: string,
): string[] {
  const value = record?.[key];
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean)
    : [];
}

/** Dizi ise kendisi, değilse boş dizi. Anahtarsız, doğrudan değer üzerinde. */
export function recordArrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}
