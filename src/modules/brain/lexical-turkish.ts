/**
 * Türkçe için sözlüksel normalleştirme — retrieval ve bağlam kapısının ortak dili.
 *
 * Neden gerekli: Türkçe eklemeli bir dildir. "makale", "makaleyi", "makalenin"
 * ve "makaleler" aynı şeydir; tam-token karşılaştırması bunları FARKLI sayar.
 * Sonuç sessiz bir kalite kaybıdır — alakalı bir hafıza bloğu ya da doküman
 * parçası yalnızca çekim eki yüzünden eşleşmez, kimse de bunu bir hata olarak
 * görmez çünkü sistem "sonuç bulamadım" demez, sadece daha kötü bir sonuç verir.
 *
 * Buradaki kök bulma kasten SÖZLÜKSÜZ ve kayıplıdır: amaç dilbilimsel doğruluk
 * değil, aynı kavramın yazımlarını tek anahtara indirmek. Aşırı budama riski
 * minimum kök uzunluğuyla sınırlanır — "yaz" ile "yazılım" birbirine karışmaz.
 *
 * SINIR: burada yalnız MORFOLOJİ vardır — hangi kelimenin "konu", hangisinin
 * "komut" olduğu semantik bir yargıdır ve bu dosyanın işi değildir. O ayrımı
 * kelime listesiyle yapmaya çalışmak bitmeyen bir bakım yüküdür; onu üreten
 * modelin kendisi yapar (belgeyi yazan model belgeye adını da koyar).
 */

/** i-ailesi tek harfe iner (İ/I/ı → i); C daemon tr_lower tablosuyla hizalı. */
export function foldTurkish(value: string): string {
  return String(value ?? "")
    .replace(/İ/g, "i")
    .replace(/I/g, "i")
    .replace(/ı/g, "i")
    .toLocaleLowerCase("tr-TR");
}

/**
 * Anlam taşımayan yüksek frekanslı kelimeler. Bunlar alakayı değil dili ölçer.
 */
export const TURKISH_STOPWORDS = new Set([
  "acaba", "ama", "ancak", "bana", "bazi", "belki", "ben", "beni", "bir",
  "biraz", "biri", "bize", "bu", "bunu", "bunun", "da", "daha", "de", "degil",
  "diye", "en", "gibi", "hangi", "hem", "her", "hic", "icin", "ile", "ise",
  "iste", "kadar", "kendi", "kim", "mi", "mu", "mü", "ne", "neden", "nasil",
  "nerede", "niye", "o", "olan", "olarak", "sana", "sen", "sonra", "sey", "su",
  "ve", "veya", "ya", "yani", "zaman", "cok", "var", "yok", "the", "a", "an",
  "and", "or", "of", "in", "on", "to", "for", "is", "are", "was", "with",
  "that", "this", "it", "be", "as", "at", "by", "what", "when", "where", "how",
  "who",
]);

const MIN_STEM_LENGTH = 4;

/**
 * Uzunluk sırasına göre denenen çekim ekleri. Yalnız EN UZUN eşleşen bir kez
 * atılır: peş peşe budama ("kitaplarımızdan" → "kit") kavramı yok eder.
 */
const INFLECTIONAL_SUFFIXES = [
  "larindan", "lerinden", "larimizi", "lerimizi", "lariniza", "lerinize",
  "larimiz", "lerimiz", "lariniz", "leriniz", "larinin", "lerinin",
  "larini", "lerini", "larina", "lerine", "larda", "lerde", "lardan",
  "lerden", "lari", "leri", "lar", "ler",
  "sinden", "sinin", "siyle", "sini", "sine",
  "imiz", "iniz", "ini", "ina", "ine",
  "dan", "den", "tan", "ten", "nin", "nun", "nün",
  "yla", "yle", "da", "de", "ta", "te", "ya", "ye",
  "yi", "yu", "yü", "im", "in", "un", "ün",
  "i", "u", "ü", "e", "a",
];

/**
 * Kayıplı ama tutarlı kök: aynı kavramın yazımları aynı anahtara iner.
 *
 * Sözlük yok, iki-aşamalı budama yok. Minimum kök uzunluğu, ekin kelimenin
 * kendisini yemesini engeller.
 */
export function stemTurkish(word: string): string {
  const folded = foldTurkish(word).replace(/['’`]/g, "");
  if (folded.length <= MIN_STEM_LENGTH) return folded;
  for (const suffix of INFLECTIONAL_SUFFIXES) {
    if (
      folded.length - suffix.length >= MIN_STEM_LENGTH &&
      folded.endsWith(suffix)
    ) {
      return folded.slice(0, folded.length - suffix.length);
    }
  }
  return folded;
}

export type TermExtractionOptions = {
  /** En fazla kaç benzersiz terim döndürülsün. */
  limit?: number;
  /** Kök bulma uygulansın mı (varsayılan: evet). */
  stem?: boolean;
};

/**
 * Metnin karşılaştırılabilir terimleri: durak kelimeler ve noktalama
 * ayıklanmış, kökleri alınmış benzersiz anahtarlar.
 */
export function contentTerms(
  text: string,
  options: TermExtractionOptions = {},
): string[] {
  const limit = options.limit ?? 24;
  const useStem = options.stem !== false;
  const raw = foldTurkish(text)
    // Kesme işareti Türkçede özel adın ekini ayırır: "Atatürk'ün" → "atatürk".
    .replace(/['’`]/g, " ")
    .split(/[^a-z0-9çğöşü_]+/u)
    .map((token) => token.trim())
    .filter(Boolean);

  const terms: string[] = [];
  const seen = new Set<string>();
  for (const token of raw) {
    if (token.length < 3) continue;
    if (TURKISH_STOPWORDS.has(token)) continue;
    const key = useStem ? stemTurkish(token) : token;
    if (!key || key.length < 3 || seen.has(key)) continue;
    seen.add(key);
    terms.push(key);
    if (terms.length >= limit) break;
  }
  return terms;
}

/**
 * İki terim kümesinin Jaccard benzerliği (0..1).
 *
 * Yakın-kopya elemede kullanılır: payda birleşim olduğu için uzun bir metin
 * yalnız büyük olduğu için benzer sayılmaz.
 */
export function jaccardSimilarity(
  left: ReadonlySet<string>,
  right: ReadonlySet<string>,
): number {
  if (left.size === 0 || right.size === 0) return 0;
  let intersection = 0;
  const [small, large] = left.size <= right.size ? [left, right] : [right, left];
  for (const term of small) {
    if (large.has(term)) intersection += 1;
  }
  const union = left.size + right.size - intersection;
  return union <= 0 ? 0 : intersection / union;
}
