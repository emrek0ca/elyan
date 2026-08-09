import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { callGeminiFreeStructured } from "./gemini-utility-client.js";
import {
  buildVisualIntentContract,
  type VisualIntentContract,
} from "./visual-intent-contract.js";

/**
 * Görsel niyetinin SEMANTİK çözümü.
 *
 * NEDEN
 * -----
 * `visual-intent-contract.ts` niyeti dokuz ayrı regex/sözlük bloğuyla
 * çıkarıyordu (SUBJECT_PATTERNS, STYLE_PATTERNS, COLOR_PATTERNS, COUNT_WORDS…).
 * Kapalı kelime listesi kullanıcının ne isteyebileceğini asla kapsayamaz:
 * "kedi" ve "araba" listede olduğu için çalışıyor, "tren" listede olmadığı
 * için `subject` BOŞ dönüyordu. Boş subject isteme
 * "Primary subject: the requested visual subject." diye yazılıyor ve model
 * konuyu kendi uyduruyordu — "tren resmi çiz" isteğine çömlekçi atölyesinde
 * kahve fincanı dönmesinin sebebi tam olarak buydu.
 *
 * Sözlüğe kelime eklemek dipsiz kuyudur ve ürüne robot hissi verir. Anlamayı
 * zaten elimizde olan modele bırakıyoruz: tek bir ucuz, yapılandırılmış
 * Gemini çağrısı niyeti, konuyu, stili ve kısıtları çıkarır.
 *
 * DAYANIKLILIK
 * ------------
 * Model çağrısı başarısız olursa (kota, ağ, bayrak kapalı) eski deterministik
 * çıkarıcıya düşülür — davranış hiçbir koşulda bugünkünden kötü olmaz.
 * Sonuç istem başına önbelleklenir; aynı tur içinde tekrar çağrı yapılmaz.
 */

const visualIntentKinds = [
  "image_generate",
  "image_edit",
  "image_continue",
  "none",
] as const;

const semanticVisualIntentSchema = z.object({
  intent: z.enum(visualIntentKinds),
  subject: z.array(z.string().trim().min(1).max(120)).max(6),
  count: z.number().int().min(1).max(12),
  style: z.string().trim().min(1).max(120).nullable(),
  add: z.array(z.string().trim().min(1).max(120)).max(8),
  remove: z.array(z.string().trim().min(1).max(120)).max(8),
  preserve: z.array(z.string().trim().min(1).max(120)).max(8),
  spatialInstruction: z.string().trim().min(1).max(240).nullable(),
  negativeConstraints: z.array(z.string().trim().min(1).max(120)).max(8),
});

type SemanticVisualIntent = z.infer<typeof semanticVisualIntentSchema>;

const semanticVisualIntentJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "intent",
    "subject",
    "count",
    "style",
    "add",
    "remove",
    "preserve",
    "spatialInstruction",
    "negativeConstraints",
  ],
  properties: {
    intent: { type: "string", enum: [...visualIntentKinds] },
    subject: { type: "array", items: { type: "string" }, maxItems: 6 },
    count: { type: "integer", minimum: 1, maximum: 12 },
    style: { type: ["string", "null"] },
    add: { type: "array", items: { type: "string" }, maxItems: 8 },
    remove: { type: "array", items: { type: "string" }, maxItems: 8 },
    preserve: { type: "array", items: { type: "string" }, maxItems: 8 },
    spatialInstruction: { type: ["string", "null"] },
    negativeConstraints: { type: "array", items: { type: "string" }, maxItems: 8 },
  },
};

const SYSTEM_PROMPT = [
  "You extract a visual-generation intent from a user's message.",
  "The user writes in any language (often Turkish). Understand meaning, never match keywords.",
  "",
  "intent:",
  "- image_generate: the user wants a NEW picture/scene/illustration/logo/photo created.",
  "- image_edit: the user wants an EXISTING image changed.",
  "- image_continue: the user wants a variation/continuation of a previous image.",
  "- none: the message is not asking for a picture at all.",
  "",
  "CRITICAL: plotting or DRAWING THE GRAPH of a mathematical function, or charting/",
  "graphing DATA (numbers, statistics, a series), is NOT image generation — return",
  "intent 'none'. The verb 'çiz'/'draw'/'göster' is used for BOTH pictures and graphs;",
  "decide by MEANING, not the verb. 'bunun grafiğini çiz' after a polynomial means",
  "plot that function (a chart), not generate a picture → none. 'bana bir kedi çiz'",
  "means a picture of a cat → image_generate.",
  "",
  "subject: the concrete thing(s) to depict, in English, as short noun phrases.",
  "Translate faithfully: 'tren' is 'train', 'çömlek atölyesi' is 'pottery studio'.",
  "Never invent a subject the user did not ask for. If genuinely unclear, return an empty list.",
  "count: how many distinct instances of the subject (default 1).",
  "style / add / remove / preserve / spatialInstruction / negativeConstraints:",
  "only fill these when the user actually expressed them; otherwise use null or an empty list.",
].join("\n");

type CacheEntry = { value: VisualIntentContract; expiresAt: number };

const CACHE_TTL_MS = 10 * 60_000;
const CACHE_MAX_ENTRIES = 500;
const cache = new Map<string, CacheEntry>();

function cacheKey(prompt: string, sourceImageCount: number): string {
  return `${sourceImageCount}|${prompt.replace(/\s+/gu, " ").trim().toLowerCase()}`;
}

function readCache(key: string): VisualIntentContract | null {
  const entry = cache.get(key);
  if (!entry) return null;
  if (entry.expiresAt <= Date.now()) {
    cache.delete(key);
    return null;
  }
  return entry.value;
}

function writeCache(key: string, value: VisualIntentContract): void {
  if (cache.size >= CACHE_MAX_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (oldest !== undefined) cache.delete(oldest);
  }
  cache.set(key, { value, expiresAt: Date.now() + CACHE_TTL_MS });
}

export function resetVisualIntentSemanticCacheForTests(): void {
  cache.clear();
}

/**
 * Semantik niyet + deterministik taban.
 *
 * Model yalnızca ANLAMAYI üretir; `sourceArtifactId` gibi sistem alanları
 * deterministik taraftan gelir çünkü onlar kullanıcının cümlesinde değil,
 * oturum durumunda yaşar.
 */
export async function resolveVisualIntentContract(
  app: FastifyInstance,
  input: {
    userId: string;
    prompt: string;
    metadata?: Record<string, unknown>;
    sourceImageCount?: number;
  },
): Promise<VisualIntentContract> {
  const deterministic = buildVisualIntentContract({
    prompt: input.prompt,
    metadata: input.metadata,
    sourceImageCount: input.sourceImageCount,
  });

  const prompt = String(input.prompt ?? "").trim();
  if (!prompt) return deterministic;

  const key = cacheKey(prompt, input.sourceImageCount ?? 0);
  const cached = readCache(key);
  if (cached) {
    return { ...cached, sourceArtifactId: deterministic.sourceArtifactId };
  }

  let semantic: SemanticVisualIntent | null = null;
  try {
    semantic = await callGeminiFreeStructured<SemanticVisualIntent>(app, {
      feature: "intent_route",
      userId: input.userId,
      system: SYSTEM_PROMPT,
      payload: {
        message: prompt,
        hasReferencedImage: (input.sourceImageCount ?? 0) > 0,
      },
      schema: semanticVisualIntentSchema,
      jsonSchema: semanticVisualIntentJsonSchema,
      maxOutputTokens: 320,
      timeoutMs: 4_000,
    });
  } catch {
    semantic = null;
  }

  if (!semantic) {
    return deterministic;
  }

  // Model "bu bir görsel isteği DEĞİL" (none) dediğinde bunu ONURLANDIR.
  // Eskiden deterministik karara düşülüyordu — ama deterministik çıkarıcı
  // "bunun/bu/şu" gibi zamirleri (CONTINUATION_PATTERNS) görsel-devam sanıp
  // intent'i image_continue/image_edit yapıyordu. Sonuç: "Bunun çözümünü yap"
  // gibi bir cümle, oturumda eski bir görsel varken bile görsel-düzenlemeye
  // düşüyordu. Model anlamı çözüp "görsel değil" dediğinde zamir-regex'ini
  // ezmeliyiz: düzenleme/devam niyetini DÜŞÜR, kararı prompt üzerindeki dürüst
  // üretim sinyaline (isVisualGenerationIntent) bırak — o da bu cümlede yoktur,
  // böylece tur sohbete düşer.
  if (semantic.intent === "none") {
    // Model "bu bir görsel isteği değil" dedi. Deterministik yol "çiz" gibi bir
    // kelime yüzünden görsel sansa bile bunu BASTIR: notAnImageRequest bayrağı
    // görsel-üretim pipeline'ını kapatır, chart/fonksiyon yolu devralır.
    return {
      ...deterministic,
      intent: "image_generate",
      sourceArtifactId: null,
      add: [],
      remove: [],
      preserve: [],
      spatialInstruction: null,
      notAnImageRequest: true,
    };
  }

  const merged: VisualIntentContract = {
    intent: semantic.intent,
    subject: semantic.subject,
    count: semantic.count,
    add: semantic.add,
    remove: semantic.remove,
    preserve: semantic.preserve,
    style: semantic.style,
    spatialInstruction: semantic.spatialInstruction,
    // Sistem alanı: hangi artefaktın düzenlendiği oturum durumundan bilinir,
    // kullanıcının cümlesinden değil.
    sourceArtifactId: deterministic.sourceArtifactId,
    negativeConstraints: semantic.negativeConstraints,
  };

  writeCache(key, merged);
  return merged;
}
