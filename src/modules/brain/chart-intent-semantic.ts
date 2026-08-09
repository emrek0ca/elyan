import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { callGeminiFreeStructured } from "./gemini-utility-client.js";
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
 * Anlamayı zaten elimizde olan modele bırakıyoruz: tek bir ucuz,
 * yapılandırılmış çağrı niyeti ve grafik ailesini çıkarır.
 *
 * DAYANIKLILIK
 * ------------
 * Model çağrısı başarısız olursa (kota, ağ, bayrak kapalı) KELİMEYE DEĞİL
 * KANITA düşülür: bağlamda gerçekten çizilebilir bir matematiksel ifade
 * varsa ve bu tur ona atıfta bulunuyorsa grafik istenmiş sayılır. Kanıt,
 * kelimeden daha güçlü bir sinyaldir — "f(x) = 2x² + 3x + 5" cümlesi
 * grafiğe çevrilebilir bir NESNEDİR, kelime eşleşmesi değil.
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

const semanticChartIntentSchema = z.object({
  wantsVisual: z.boolean(),
  family: z.enum(chartFamilies),
});

const semanticChartIntentJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["wantsVisual", "family"],
  properties: {
    wantsVisual: {
      type: "boolean",
      description:
        "True when the user's latest turn asks to SEE something plotted/drawn/visualised, including indirect phrasings and follow-ups that refer to a previous answer.",
    },
    family: {
      type: "string",
      enum: [...chartFamilies],
      description:
        "function = a 2D curve y=f(x); surface = a 3D surface z=f(x,y); data = a numeric series/comparison/trend; none = no visual wanted.",
    },
  },
} as const;

const SYSTEM_PROMPT = [
  "You decide whether the user's latest chat turn asks for a VISUAL plot.",
  "You are given the latest user message and the recent conversation.",
  "Answer only about intent — never about feasibility, and never invent data.",
  "A short follow-up like 'draw it', 'show me', 'what does it look like' refers to the previous assistant answer: resolve it against that context.",
  "Choose family from what would actually be plotted: a single-variable formula is 'function', a two-variable formula is 'surface', measured/tabular numbers over categories or time are 'data'.",
  "If the turn is conversational, explanatory, or asks for text, answer wantsVisual=false and family='none'.",
].join(" ");

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
 * Model çağrısı yoksa/başarısızsa: bağlamda ÇİZİLEBİLİR bir ifade var mı?
 * Varsa ve bu tur kısa bir devam turuysa (kendi başına yeni bir konu
 * açmıyorsa) grafiğin istendiğini kabul ediyoruz. Bu bir kelime eşleşmesi
 * değil; bağlamdaki nesnenin TÜRÜNE bakan bir çıkarım.
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
 * Semantik niyet + kanıt tabanı.
 *
 * Model YALNIZCA anlamayı üretir; verinin kendisi (ifade, sayısal seri)
 * deterministik taraftan gelir — model hiçbir zaman sayı uydurmaz.
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

  try {
    const semantic = await callGeminiFreeStructured(app, {
      feature: "intent_route",
      userId: input.userId,
      system: SYSTEM_PROMPT,
      payload: {
        latestUserMessage: prompt.slice(0, 1_200),
        recentConversation: recentContext.map((text) => text.slice(0, 600)),
        hasNumericSeries: (input.numericPointCount ?? 0) >= 2,
      },
      schema: semanticChartIntentSchema,
      jsonSchema: semanticChartIntentJsonSchema as unknown as Record<string, unknown>,
      maxOutputTokens: 120,
      timeoutMs: 2_500,
    });
    if (semantic) {
      const resolved: ChartIntent = semantic.wantsVisual
        ? {
            wantsChart: true,
            // Model aileyi söyler, ama elimizde SOMUT kanıt varsa
            // (iki değişkenli ifade gibi) kanıt kazanır — veri türünü
            // veri belirler, cümle değil.
            family:
              evidence.wantsChart && evidence.family !== "data"
                ? evidence.family
                : semantic.family === "none"
                  ? evidence.family === "none"
                    ? "data"
                    : evidence.family
                  : semantic.family,
            source: "semantic",
          }
        : // Model "görsel istenmiyor" dese bile, bağlamda çizilebilir bir
          // ifade VAR ve kullanıcı ona atıf yapıyorsa kanıt kazanır:
          // yanlış negatif, kullanıcıya boş cevap olarak döner.
          evidence;
      writeCache(key, resolved);
      return resolved;
    }
  } catch (error) {
    app.log.debug?.(
      { error: error instanceof Error ? error.message : "chart_intent_failed" },
      "semantic chart intent unavailable; falling back to evidence",
    );
  }

  writeCache(key, evidence);
  return evidence;
}
