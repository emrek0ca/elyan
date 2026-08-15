import type { FastifyInstance } from "fastify";
import {
  primeWidgetShapeSemantic,
  resolveWidgetShapeSemantic,
} from "../../core/understanding/widget-shape-semantic.js";
import { requestsChartOutput } from "../../core/understanding/structured-output-policy.js";
import { extractPlottableExpression } from "./deterministic-chart.js";

/**
 * Grafik niyetinin SEMANTİK çözümü.
 *
 * NEDEN
 * -----
 * "Kullanıcı grafik mi istiyor?" sorusu `isExplicitChartRequest` ile
 * yanıtlanıyordu: kapalı bir kelime listesi (grafik|chart|plot|çiz|görselleştir…).
 * Kapalı liste kullanıcının ne diyebileceğini asla kapsayamaz —
 * "bunu görebilir miyim", "şeklini göster", "nasıl bir eğri bu", "resmet"
 * hepsi listede yok. Listeye kelime eklemek dipsiz kuyudur; aylardır
 * bitmemesinin sebebi tam olarak bu desendi.
 *
 * SAĞLAYICIDAN KURTARILDI
 * -----------------------
 * Bu modül doğru çerçevelenmişti ama kararı TEK BİR SAĞLAYICIYA (Gemini
 * ücretsiz katmanı, `callGeminiFreeStructured`) bağlıydı. O yol bu projede
 * pratikte hiç çalışmadı: bayrak/kota/gizlilik kapılarının herhangi biri
 * kapalıyken çağrı sessizce düşüyor ve karar her seferinde kanıt tabanına
 * iniyordu. Yani "semantik grafik niyeti" adında bir modül vardı ve HİÇ
 * semantik karar üretmiyordu.
 *
 * Artık karar `widget-shape-semantic` + `structured-output-policy` ile aynı
 * TEK SÖZLEŞMEDEN okunuyor: e5 prototip benzerliği (varsa), hash prototipi
 * (yedek), kelime listesi (kesin durumlar). Hiçbir sağlayıcıya zorunlu bağlı
 * değil — ağ olmadan da karar üretir. Bu sayede zarf (`understanding-envelope`),
 * grounding (`web-grounding`) ve tamamlanma yolu aynı turda AYNI cevabı verir;
 * daha önce üçü ayrı kaynaktan karar aldığı için çelişiyorlardı.
 *
 * DAYANIKLILIK
 * ------------
 * Niyet "hayır" dese bile bağlamda gerçekten çizilebilir bir matematiksel
 * ifade varsa KANIT kazanır: "f(x) = 2x² + 3x + 5" cümlesi grafiğe
 * çevrilebilir bir NESNEDİR, kelime eşleşmesi değil. Yanlış negatif
 * kullanıcıya boş cevap olarak döner, o yüzden bu yön bilinçli olarak açık.
 */

const chartFamilies = ["function", "surface", "data", "none"] as const;
export type ChartFamily = (typeof chartFamilies)[number];

export type ChartIntent = {
  /** Bu turda çizilebilir bir görsel bekleniyor mu? */
  wantsChart: boolean;
  /** Hangi aile: 2B fonksiyon, 3B yüzey ya da sayısal veri serisi. */
  family: ChartFamily;
  /** Kararın nereden geldiği — telemetri ve hata ayıklama için. */
  source: "semantic" | "evidence" | "none";
};

const NO_CHART: ChartIntent = { wantsChart: false, family: "none", source: "none" };

const CACHE_TTL_MS = 5 * 60_000;
const CACHE_MAX_ENTRIES = 300;

type CacheEntry = { value: ChartIntent; expiresAt: number };
const cache = new Map<string, CacheEntry>();

function cacheKey(userId: string, prompt: string, contextHead: string): string {
  // Kullanıcı kapsamlı anahtar: farklı kullanıcıların turları ASLA aynı
  // kovayı paylaşmaz (kullanıcılar arası sızıntı kırmızı çizgisi).
  return `${userId}|${prompt.replace(/\s+/gu, " ").trim()}|${contextHead.slice(0, 160)}`;
}

function readCache(key: string): ChartIntent | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (entry.expiresAt <= Date.now()) {
    cache.delete(key);
    return null;
  }
  return entry.value;
}

function writeCache(key: string, value: ChartIntent): void {
  if (cache.size >= CACHE_MAX_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(key, { value, expiresAt: Date.now() + CACHE_TTL_MS });
}

export function resetChartIntentSemanticCacheForTests(): void {
  cache.clear();
}

/**
 * Kelimesiz, kanıta dayalı taban.
 *
 * Bağlamda ÇİZİLEBİLİR bir ifade var mı? Varsa grafiğin istendiğini kabul
 * ediyoruz. Bu bir kelime eşleşmesi değil; bağlamdaki nesnenin TÜRÜNE bakan
 * bir çıkarım.
 */
export function chartIntentFromEvidence(input: {
  prompt: string;
  contextTexts?: Array<string | null | undefined>;
  numericPointCount?: number;
}): ChartIntent {
  const expression = extractPlottableExpression([
    input.prompt,
    ...(input.contextTexts ?? []),
  ]);
  if (expression) {
    return {
      wantsChart: true,
      family: expression.variables.length === 2 ? "surface" : "function",
      source: "evidence",
    };
  }
  if ((input.numericPointCount ?? 0) >= 2) {
    return { wantsChart: true, family: "data", source: "evidence" };
  }
  return NO_CHART;
}

/**
 * Aileyi seçerken KANIT cümleden önce gelir: iki değişkenli bir ifade
 * varsa aile "surface"tır, kullanıcı ne derse desin. Veri türünü veri
 * belirler.
 */
function resolveFamily(evidence: ChartIntent, shape: string | null): ChartFamily {
  if (shape === "math_surface_3d") {
    return "surface";
  }
  if (evidence.wantsChart && evidence.family !== "data" && evidence.family !== "none") {
    return evidence.family;
  }
  return "data";
}

/**
 * Semantik niyet + kanıt tabanı.
 *
 * Model YALNIZCA anlamayı üretir; verinin kendisi (ifade, sayısal seri)
 * deterministik taraftan gelir — hiçbir zaman sayı uydurulmaz.
 *
 * `async` kalıyor çünkü e5 ısıtması ağ/işlem gerektirebiliyor; ısıtma
 * başarısız olursa senkron okuma hash prototipine düşer ve karar yine üretilir.
 */
export async function resolveChartIntent(
  app: FastifyInstance,
  input: {
    userId: string;
    prompt: string;
    contextTexts?: Array<string | null | undefined>;
    numericPointCount?: number;
  },
): Promise<ChartIntent> {
  const evidence = chartIntentFromEvidence(input);
  const prompt = String(input.prompt ?? "").trim();
  if (!prompt) {
    return evidence;
  }

  const recentContext = (input.contextTexts ?? [])
    .map((text) => String(text ?? "").trim())
    .filter(Boolean)
    .slice(0, 4);
  const key = cacheKey(input.userId, prompt, recentContext[0] ?? "");
  const cached = readCache(key);
  if (cached) {
    return cached;
  }

  // Isıtma: e5 kararını bir kez hesaplayıp önbelleğe koyar. Başarısız olursa
  // sessizce hash yoluna düşülür — sağlayıcı arızası kararı TIKAMAZ.
  await primeWidgetShapeSemantic(prompt).catch(() => undefined);

  const shape = resolveWidgetShapeSemantic(prompt)?.shape ?? null;
  const resolved: ChartIntent = requestsChartOutput(prompt)
    ? { wantsChart: true, family: resolveFamily(evidence, shape), source: "semantic" }
    : // Niyet "grafik değil" diyor. Ama bağlamda çizilebilir bir ifade VARSA
      // kanıt kazanır — yanlış negatif kullanıcıya boş cevap olarak döner.
      evidence;

  app.log?.debug?.(
    { wantsChart: resolved.wantsChart, family: resolved.family, source: resolved.source },
    "chart intent resolved",
  );
  writeCache(key, resolved);
  return resolved;
}
