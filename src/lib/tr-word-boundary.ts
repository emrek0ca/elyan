/**
 * JS'de `\b`, ASCII `\w` (`[A-Za-z0-9_]`) tabanlıdır. Türkçe harfler (ı, ş, ğ,
 * ü, ö, ç, İ…) kelime karakteri sayılmadığı için `\bsağlayıcı\b` gibi bir kalıp
 * beklenen yerde eşleşmez ve kural sessizce ölür. Bu, kimlik kapısında ve iç
 * yapılandırma savunmalarında gerçek kaçaklara yol açtı.
 *
 * `UNICODE_WORD_BOUNDARY`, `\b`'nin birebir Unicode karşılığıdır: ya kelime
 * dışından kelime içine, ya da kelime içinden kelime dışına geçiş. `/u` bayrağı
 * zorunludur.
 */
const WORD_CHAR = String.raw`[\p{L}\p{N}_]`;

export const UNICODE_WORD_BOUNDARY =
  `(?:(?<!${WORD_CHAR})(?=${WORD_CHAR})|(?<=${WORD_CHAR})(?!${WORD_CHAR}))`;

/**
 * Kaynak içindeki her `\b`'yi Unicode karşılığıyla değiştirip `/u` bayraklı bir
 * RegExp üretir. Kaçışlanmış `\\b` (literal backspace) dokunulmadan bırakılır.
 */
export function unicodeWordPattern(source: string, flags = ""): RegExp {
  const rewritten = source.replace(/(\\*)\\b/g, (match, backslashes: string) => {
    // Önündeki ters bölü sayısı tekse `\b` gerçekten sınır belirtecidir;
    // çiftse (`\\b`) literal olarak kaçışlanmıştır ve korunmalıdır.
    if (backslashes.length % 2 === 1) {
      return match;
    }
    return `${backslashes}${UNICODE_WORD_BOUNDARY}`;
  });
  const normalizedFlags = flags.includes("u") ? flags : `${flags}u`;
  return new RegExp(rewritten, normalizedFlags);
}
