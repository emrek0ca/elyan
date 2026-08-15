import { buildHashedKnowledgeEmbedding } from "../../modules/brain/retrieval.js";
import { rankSemanticTextCandidates } from "./intent-semantic.js";

/**
 * Widget biçiminin SEMANTİK çözümü.
 *
 * NEDEN
 * -----
 * `structured-output-policy.ts` "kullanıcı hangi widget'ı istiyor?" sorusunu
 * 24 düzenli ifadeyle yanıtlıyordu: kapalı kelime listeleri
 * (tablo|table|matris…, grafik|chart|plot|çiz…, latex|denklem|integral…).
 * Kapalı liste kullanıcının ne diyebileceğini asla kapsayamaz. Listede
 * olmayan ve prodüksiyonda düşen ifadeler: "bunu yan yana koyup göster",
 * "hangisi daha iyi karşılaştıralım", "şeklini görebilir miyim", "nasıl bir
 * eğri bu", "bunun matematiğini yaz". Listeye kelime eklemek dipsiz kuyu —
 * projenin kendi kuralı da niyet kararının semantik olmasını söylüyor.
 *
 * `chart-intent-semantic.ts` bu işi doğru çerçeveledi ama TEK BİR SAĞLAYICIYA
 * (Gemini) bağlandı. O sağlayıcı bu projede erişilebilir değil (metin
 * modelleri 403, görsel modelleri 429), yani semantik yol pratikte hiç
 * çalışmıyor ve karar sessizce kelimeye geri düşüyor.
 *
 * NASIL
 * -----
 * Bu modül `classifyIntentSemantic` ile AYNI deseni kullanıyor: her biçim
 * için bir avuç tohum cümlesinin hash gömme ortalaması bir prototip vektör
 * veriyor, istem en yakın prototipe atanıyor. Tamamen senkron, model yok,
 * ağ yok, sağlayıcı yok — yani her zaman çalışır.
 *
 * "prose" prototipleri BİLEREK var: sıradan sohbetin bir widget'a çekilmemesi
 * için düz metin de bir aday. Kazanan biçim düz metni belirgin bir farkla
 * geçemiyorsa karar `null` — kararsızlıkta widget'a zorlamak, widget'ı
 * kaçırmaktan daha kötüdür (kullanıcı istemediği bir tabloyla karşılaşır).
 */

export type SemanticWidgetShape =
  | "table"
  | "chart"
  | "math_surface_3d"
  | "math"
  | "svg"
  | "prose";

const SHAPE_SEED_PHRASES: Record<SemanticWidgetShape, string[]> = {
  table: [
    "bunları yan yana koyup karşılaştır",
    "hangisi daha iyi, özelliklerini karşılıklı göster",
    "her birinin fiyatını ve özelliğini düzenli göster",
    "bu verileri satır sütun halinde düzenle",
    "tablo olarak hazırla",
    "compare these side by side in a grid",
    "lay out the specs for each option",
    "give me a spreadsheet of this data",
  ],
  chart: [
    "bunun şeklini görebilir miyim",
    "nasıl bir eğri çıkıyor",
    "zamana göre nasıl değiştiğini göster",
    "bu sayıların dağılımını görselleştir",
    "grafiğini çiz",
    "satışların trendini görmek istiyorum",
    "plot this function",
    "show me the trend over time as a graph",
    "visualise this distribution",
  ],
  math_surface_3d: [
    "üç boyutlu yüzeyini çiz",
    "z = f(x, y) yüzeyini göster",
    "iki değişkenli fonksiyonun yüzeyi nasıl görünüyor",
    "3d surface plot of this function",
    "render the mesh of this two variable function",
  ],
  math: [
    "bu denklemi çöz",
    "türevini al ve adımları yaz",
    "integralini hesapla",
    "bunun matematiğini yaz",
    "formülünü çıkar",
    "ispatını göster",
    "solve this equation step by step",
    "write the closed form expression",
    "bana bir polinom yaz",
  ],
  svg: [
    "bunun şemasını çiz",
    "akış diyagramını göster",
    "kutular ve oklarla anlat",
    "mimarisini şema olarak çiz",
    "draw a diagram of this flow",
    "sketch the architecture as boxes and arrows",
  ],
  prose: [
    "bunu bana açıkla",
    "kısaca anlat",
    "ne düşünüyorsun",
    "nasılsın bugün",
    "bu konuda ne yapmalıyım",
    "bir mail taslağı yaz",
    "şu metni düzelt",
    "explain this to me",
    "what do you think about it",
    "summarise this in a few sentences",
    "help me write an email",
  ],
};

function averagePrototype(phrases: string[]): number[] {
  const vectors = phrases.map((phrase) => buildHashedKnowledgeEmbedding(phrase));
  const dim = vectors[0]?.length ?? 0;
  const sum = new Array<number>(dim).fill(0);
  for (const vector of vectors) {
    for (let i = 0; i < dim; i += 1) {
      sum[i] += vector[i] ?? 0;
    }
  }
  const magnitude = Math.sqrt(sum.reduce((acc, value) => acc + value * value, 0));
  return magnitude > 0 ? sum.map((value) => value / magnitude) : sum;
}

const SHAPE_PROTOTYPES: Array<{ shape: SemanticWidgetShape; vector: number[] }> =
  (Object.entries(SHAPE_SEED_PHRASES) as Array<[SemanticWidgetShape, string[]]>).map(
    ([shape, phrases]) => ({ shape, vector: averagePrototype(phrases) }),
  );

function dot(a: number[], b: number[]): number {
  const n = Math.min(a.length, b.length);
  let sum = 0;
  for (let i = 0; i < n; i += 1) {
    sum += a[i] * b[i];
  }
  return sum;
}

export type SemanticWidgetShapeMatch = {
  shape: Exclude<SemanticWidgetShape, "prose">;
  score: number;
  /** Düz metin prototipine karşı üstünlük. Kararın gücü budur. */
  margin: number;
};

/**
 * e5 için biçim tarifleri. Prototip cümleleri tek bir tarif metnine
 * birleştiriyoruz: transformer, ayrı ayrı puanlanan kısa cümlelerden çok
 * bağlamı olan bir tarifle daha iyi ayrışıyor.
 */
const SHAPE_DESCRIPTIONS: Array<{ id: SemanticWidgetShape; description: string }> =
  (Object.entries(SHAPE_SEED_PHRASES) as Array<[SemanticWidgetShape, string[]]>).map(
    ([shape, phrases]) => ({ id: shape, description: phrases.join(". ") }),
  );

const TRANSFORMER_TTL_MS = 5 * 60_000;
const TRANSFORMER_MAX_ENTRIES = 300;
type TransformerEntry = { value: SemanticWidgetShapeMatch | null; expiresAt: number };
const transformerCache = new Map<string, TransformerEntry>();

function normalize(text: string): string {
  return String(text ?? "").replace(/\s+/gu, " ").trim();
}

function readTransformerCache(key: string): TransformerEntry | null {
  const entry = transformerCache.get(key);
  if (!entry) return null;
  if (entry.expiresAt <= Date.now()) {
    transformerCache.delete(key);
    return null;
  }
  return entry;
}

function writeTransformerCache(key: string, value: SemanticWidgetShapeMatch | null): void {
  if (transformerCache.size >= TRANSFORMER_MAX_ENTRIES) {
    const oldest = transformerCache.keys().next().value;
    if (oldest !== undefined) transformerCache.delete(oldest);
  }
  transformerCache.set(key, { value, expiresAt: Date.now() + TRANSFORMER_TTL_MS });
}

export function resetWidgetShapeSemanticCacheForTests(): void {
  transformerCache.clear();
}

/**
 * Turun biçim kararını e5 ile ÖNCEDEN hesaplar ve önbelleğe koyar.
 *
 * Hash gömme sözcük torbasıdır: farklı kelimelerle kurulmuş parafrazı
 * kaçırıyor — ölçüldü, "bunları yan yana koyup göster" düz metne düşüyordu.
 * Bu modülün var oluş sebebi tam olarak o cümlelerdi, dolayısıyla gerçek
 * semantik model şart. Karar senkron bir fonksiyondan okunduğu için (üç ayrı
 * istem kurucusu, hepsi senkron), model çağrısını tur başında bir kez yapıp
 * sonucu önbellekten okutuyoruz.
 *
 * Model erişilemezse önbellek boş kalır ve senkron yol hash'e düşer: daha
 * dar ama çalışan bir karar. Bu modül HİÇBİR sağlayıcıya zorunlu bağlı
 * değil — `chart-intent-semantic.ts`'in Gemini'ye bağlanıp pratikte hiç
 * çalışmaması bu yüzden tekrarlanmıyor.
 */
export async function primeWidgetShapeSemantic(text: string): Promise<void> {
  const trimmed = normalize(text);
  if (trimmed.length < 8 || readTransformerCache(trimmed)) {
    return;
  }
  try {
    const match = await rankSemanticTextCandidates(trimmed, SHAPE_DESCRIPTIONS, {
      transformerMinScore: 0.7,
      transformerMinMargin: 0.01,
      // Hash yolu burada KAPALI: `rankSemanticTextCandidates` model yoksa
      // hash'e düşüyor, ama bu modülün kendi hash yolu prototip ortalamasıyla
      // çalışıyor ve daha iyi kalibre. İkisini karıştırmıyoruz.
      hashMinScore: 2,
      hashMinMargin: 2,
    });
    const resolved =
      match && match.source === "transformer" && match.id !== "prose"
        ? {
            shape: match.id as Exclude<SemanticWidgetShape, "prose">,
            score: match.score,
            margin: match.margin,
          }
        : null;
    writeTransformerCache(trimmed, resolved);
  } catch {
    // Sessiz: senkron yol hash'e düşer, karar üretilmeye devam eder.
  }
}

/**
 * En yakın biçim prototipini döndürür; kazanan düz metinse ya da üstünlük
 * eşiği aşılmıyorsa `null`.
 *
 * Önce `primeWidgetShapeSemantic` ile hesaplanmış e5 kararı okunur; yoksa
 * hash prototipine düşülür.
 *
 * Eşikler bilinçli olarak TUTUCU: bu katman kelime listelerinin YERİNE değil,
 * onların GÖREMEDİĞİ parafrazlar için var. Kelime eşleşmesi zaten yakaladığı
 * durumlarda çağrılmıyor.
 */
export function resolveWidgetShapeSemantic(
  text: string,
  options: { minScore?: number; minMargin?: number } = {},
): SemanticWidgetShapeMatch | null {
  const trimmed = normalize(text);
  if (trimmed.length < 8) {
    // Çok kısa turlar ("tamam", "peki") anlamsal olarak her şeye benzer;
    // bu aralıkta prototip mesafesi bilgi taşımıyor.
    return null;
  }
  const cached = readTransformerCache(trimmed);
  if (cached) {
    return cached.value;
  }
  const queryVector = buildHashedKnowledgeEmbedding(trimmed);
  const ranked = SHAPE_PROTOTYPES.map((prototype) => ({
    shape: prototype.shape,
    score: dot(queryVector, prototype.vector),
  })).sort((left, right) => right.score - left.score);

  const best = ranked[0];
  if (!best || best.shape === "prose") {
    return null;
  }
  const proseScore = ranked.find((entry) => entry.shape === "prose")?.score ?? 0;
  const margin = best.score - proseScore;
  if (best.score < (options.minScore ?? 0.34) || margin < (options.minMargin ?? 0.06)) {
    return null;
  }
  return {
    shape: best.shape as Exclude<SemanticWidgetShape, "prose">,
    score: best.score,
    margin,
  };
}
