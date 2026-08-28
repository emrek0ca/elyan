/**
 * Metin normalleştirme — TEK kaynak, DÜRÜST adlarla.
 *
 * NEDEN VAR: `compactText` adı kod tabanında kırk iki kez yeniden yazılmıştı
 * ve altında BEŞ FARKLI DAVRANIŞ birikmişti:
 *
 *   11 kopya  String(value ?? "") + iç boşlukları sıkıştır + kırp
 *    8 kopya  value.replace(...)  (aynı davranış, ama null'da patlar)
 *    8 kopya  String(value ?? "") + sıkıştır + kırp, `string` tipli
 *    4 kopya  typeof value === "string" ? value.trim() : ""   ← SIKIŞTIRMAZ
 *    2 kopya  sıkıştır + kırp + belirli uzunlukta kes
 *
 * Yani bir modülde `compactText("a   b")` → `"a b"` iken, başka bir modülde
 * aynı isimli fonksiyon `"a   b"` bırakıyordu. Normalleştirilmiş metni modül
 * sınırı boyunca karşılaştıran her karar — "bu başlık isteğin kendisi mi",
 * "bu iki metin aynı konu mu" — hangi dosyada çalıştığına göre farklı cevap
 * veriyordu. Kovalanması en zor hata sınıfı buydu: kod her iki tarafta da
 * doğru görünüyor.
 *
 * ÇÖZÜM ADLANDIRMADIR. `compactText` adı, ne yaptığını söylemediği için beş
 * davranışı aynı çatı altında saklayabildi. Aşağıdaki adlar ne yaptıklarını
 * söylüyor; bir çağıranın yanlışlıkla diğerini seçmesi artık okunur bir hata.
 */

/**
 * İç boşlukları TEK boşluğa indirir ve uçları kırpar.
 * `"  a   b \n c "` → `"a b c"`. Metinleri karşılaştırmak için doğru olan bu.
 */
export function collapseWhitespace(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

/**
 * YALNIZCA uçları kırpar; iç boşluklara dokunmaz.
 * `"a   b"` → `"a   b"`. İç aralığın anlamlı olduğu yerlerde (kod, biçimli
 * metin, kullanıcının yazdığı gövde) doğru olan budur.
 *
 * Metin olmayan girdi `""` döner — kopyaların davranışı buydu ve korunuyor.
 */
export function trimOnly(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Sıkıştırır, kırpar ve gerekiyorsa `max` uzunluğunda keser.
 * Kesme yapıldığında sona tek karakterlik bir üç nokta konur.
 */
export function truncateText(value: unknown, max: number): string {
  const normalized = collapseWhitespace(value);
  if (max <= 0) return "";
  return normalized.length <= max
    ? normalized
    : `${normalized.slice(0, max - 1).trimEnd()}…`;
}

/**
 * Kırpılmış metin; metin değilse ya da boşsa `null`.
 *
 * `""` ile `null` arasındaki farkı ÖNEMSEYEN çağıranlar için. Otuz kopyanın
 * yarısı bu şekildeydi ve boş metni "yok" saymak istiyordu.
 */
export function asNonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** Sonlu sayı ise kendisi, değilse `null`. */
export function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Türkçe aksanları düşürür: "doğrulayamıyorum" → "dogrulayamiyorum".
 *
 * NEDEN GEREKLİ: model ve kullanıcı Türkçeyi çoğu zaman aksansız yazar. Bir
 * kapının deseni yalnız aksanlı yazılmışsa, aksansız yazımda SESSİZCE AÇILIR
 * — yani yakalaması gereken metin doğrudan kullanıcıya gider.
 *
 * Bu tam olarak ölçülmüş bir hatadır: `ROBOTIC_PHRASE_PATTERNS` yalnız
 * `/doğrulayamıyorum/` yazıyordu ve olgusallık kapısının kendi cümlesi
 * aksansız olduğu için listeye hiç takılmıyordu (bkz. `response-policy`).
 *
 * Deseni ikiye katlamak (`doğrula|dogrula`) her yeni giriş için iki kat bakım
 * demektir ve biri unutulduğunda kapı yine sessizce açılır. Doğru olan METNİ
 * tek yazıma indirip deseni bir kez yazmaktır.
 */
export function foldTurkishDiacritics(value: string): string {
  return String(value ?? "")
    .replace(/İ/g, "I")
    .replace(/ı/g, "i")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}
