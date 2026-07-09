import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import type { FastifyInstance } from "fastify";
import type { ArtifactInput } from "../../contracts/domain.js";
import { tryAcquireLoadSheddingPermit } from "../../lib/reliability/load-shedding.js";
import {
  isCircuitCallAllowed,
  recordCircuitFailure,
  recordCircuitSuccess,
} from "../../lib/reliability/circuit-breaker.js";
import type { ReliabilityStore } from "../../lib/reliability/redis.js";
import {
  assertMonthlyImageGenerationAllowed,
  recordImageGenerationUsage,
} from "../billing/usage-ledger.js";

type HostedImageArtifactInput = {
  prompt: string;
  responseText: string;
  metadata?: Record<string, unknown>;
  userId?: string;
  taskId?: string;
};

// ── Çoklu-kullanıcı dayanıklılık ayarları ─────────────────────────────────
// Görsel üretimi pahalı (≤60s) tek bir dış çağrı. Tek kullanıcının tüm
// kapasiteyi yemesini, bir sağlayıcı tıkandığında (ör. 429 prepayment
// depleted) her isteğin timeout slotunu boşa harcamasını ve aynı istemin
// tekrar tekrar dış sağlayıcıya gitmesini engelleyen katman.
const IMAGE_GLOBAL_MAX_CONCURRENT = 6;
const IMAGE_GLOBAL_PERMIT_TTL_MS = 90_000;
const IMAGE_GLOBAL_PERMIT_RETRIES = 3;
const IMAGE_GLOBAL_PERMIT_RETRY_DELAY_MS = 350;
// Kullanıcı başına aynı anda en fazla bu kadar üretim; aşınca metin cevabı
// yine döner ama görsel bu turda üretilmez (adil sıralama).
const IMAGE_MAX_INFLIGHT_PER_USER = 2;
const IMAGE_PER_USER_TTL_MS = 90_000;
// Sağlayıcı+model bazında devre kesici.
const IMAGE_CIRCUIT_FAILURE_THRESHOLD = 2;
const IMAGE_CIRCUIT_OPEN_MS = 60_000;
// 429/402/403 (kota/ödeme) hataları kredi yüklenene kadar sürer; devreyi daha
// uzun süre açık tut ki her istek boşuna dış çağrı yapmasın.
const IMAGE_CIRCUIT_QUOTA_OPEN_MS = 5 * 60_000;
// Aynı istemi eşzamanlı üreten N isteği tek dış çağrıya indirger (single-flight)
// ve kısa süreli sonuç önbelleği ile tekrar istekleri anında karşılar.
// Aynı istem (aynı oran/boyut/kalite) 6 saat boyunca tek dış çağrıyla
// paylaşılır — "kedi resmi çiz" gibi popüler istemlerde en büyük tasarruf.
const IMAGE_CACHE_TTL_MS = 6 * 60 * 60_000;
const IMAGE_CACHE_MAX_BASE64_LENGTH = 1_800_000; // ~1.3MB görsel; daha büyüğü önbelleğe alınmaz
const IMAGE_SINGLEFLIGHT_LOCK_TTL_MS = 75_000;
const IMAGE_SINGLEFLIGHT_WAIT_MS = 12_000;
const IMAGE_SINGLEFLIGHT_POLL_MS = 300;
// Kısa pencere rate limit: günlük kota maliyeti kontrol eder, bu katman ise
// ani trafik patlamalarında provider ve CPU yükünü yumuşatır. Cache hit'ler
// bu sayacı tüketmez.
const IMAGE_RATE_LIMIT_WINDOW_MS = 5 * 60_000;
const IMAGE_RATE_LIMIT_GLOBAL_WINDOW_MS = 60_000;
const IMAGE_RATE_LIMIT_GLOBAL_MAX = 24;

const IMAGE_RATE_LIMITS_BY_PLAN: Record<string, number> = {
  free: 2,
  solo: 5,
  pro: 8,
};

type CachedImagePayload = {
  base64: string;
  mimeType: string;
  revisedPrompt: string | null;
  model: string;
};

type ImageGenerationUsageAllowance = {
  planCode: string;
  limit: number;
  used: number;
  remaining: number;
};

function resolveReliabilityStore(app: FastifyInstance): ReliabilityStore | null {
  return app.services?.reliability?.store ?? null;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function imageCircuitKey(provider: string, model: string): string {
  return `circuit:image:${provider}:${model}`;
}

/** Dış sağlayıcı hatasını sınıflandırır: kota/ödeme mi, geçici hata mı? */
function classifyProviderFailure(status: number | null): "quota" | "error" {
  if (status === 429 || status === 402 || status === 403) {
    return "quota";
  }
  return "error";
}

type HostedImageProviderConfig = {
  provider: "gemini" | "openai";
  apiKey: string;
  baseUrl: string;
  model: string;
  source: string;
  imageSize?: "1K" | "2K" | "4K";
};

export type HostedImageArtifactResult = {
  artifact: ArtifactInput;
  binaryBody: Uint8Array;
  mimeType: string;
  model: string;
  previewText: string;
  revisedPrompt: string | null;
};

const CREATIVE_IMAGE_REQUEST_PATTERNS = [
  /(görsel|gorsel|resim|resmi|resmini|afiş|afis|poster|banner|kapak|logo|ikon|avatar|maskot|çizim|cizim).{0,80}(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|çiz|ciz)/i,
  /(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|çiz|ciz).{0,80}(görsel|gorsel|resim|resmi|resmini|afiş|afis|poster|banner|kapak|logo|ikon|avatar|maskot|çizim|cizim)/i,
  /\b(görsel|gorsel|resim|resmi|resmini|image|afiş|afis|poster|banner|kapak|thumbnail|illüstrasyon|illustration|mockup|cover|logo|ikon|avatar|maskot|sticker|çizim|cizim)\b.*\b(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|çiz|ciz|draw|paint|sketch|design|generate|create)\b/i,
  /\b(üret|uret|oluştur|olustur|hazırla|hazirla|tasarla|çiz|ciz|draw|paint|sketch|design|generate|create)\b.*\b(görsel|gorsel|resim|resmi|resmini|image|afiş|afis|poster|banner|kapak|thumbnail|illüstrasyon|illustration|mockup|cover|logo|ikon|avatar|maskot|sticker|çizim|cizim)\b/i,
  /\b[\p{L}\p{N}_-]{2,}(?:\s+[\p{L}\p{N}_-]{2,}){0,6}\s+(resmi|resmini|çizimi|cizimi)\s*(çiz|ciz|draw|paint|sketch)\b/iu,
  /\b(afiş|afis|poster|banner|kapak|thumbnail)\b/i,
  // Emir/istek kipi çizim komutları — "resim/görsel" ismi OLMADAN da yakala:
  // "bana kırmızı bir araba çiz", "bir kedi çiz", "araba çizer misin", "çizsene".
  // Türkçe "ç" ASCII \b sınırını bozduğu için Unicode-farkında (\p{L}) sınır
  // kullanılır; "çizgi/çizelge/çizik" gibi çizim-dışı kelimeler eşleşmez.
  /(?<!\p{L})(çiz|ciz)(er|ersen|sene|senize|ebilir|iver|in|iniz|elim|sin)?(?!\p{L})/iu,
  // İngilizce çizim fiilleri: "draw me a red car", "sketch a cat".
  /\b(draw|sketch|paint|illustrate)\b/i,
];

const NON_CREATIVE_EXPORT_PATTERNS = [
  /\b(png|jpg|jpeg|webp)\b.*\b(ver|çevir|cevir|dönüştür|donustur|kaydet)\b/i,
  /\b(ver|çevir|cevir|dönüştür|donustur|kaydet)\b.*\b(png|jpg|jpeg|webp)\b/i,
];

// "Grafiğini çiz", "fonksiyonun grafiği", "plot the function" gibi istekler
// GÖRSEL ÜRETİMİ DEĞİL, matematiksel/veri grafiği (chart/math bloğu) ister.
// "çiz/draw" fiili tek başına görsel üretimini tetiklediği için ("grafiğini
// ÇİZ" → stok fotoğraf), veri-görselleştirme sinyali varsa hosted image
// tamamen devre dışı bırakılır ve karar akıllı inference'a (chart pipeline)
// bırakılır. Sanatsal "grafik tasarım/afiş" istekleri "tasarım/afiş" gibi
// yaratıcı kelimelerle zaten ayrışır; burada yalnızca veri/matematik
// grafiği sinyalleri yakalanır.
const DATA_VISUALIZATION_REQUEST_PATTERNS = [
  /\bgrafi(k|ğ|g)\w*\b/i, // grafik, grafiği, grafiğini, grafikte
  /\b(plot|chart|diagram|diyagram|histogram|scatter|dağılım grafiği|dagilim grafigi)\b/i,
  /\b(fonksiyon|denklem|polinom|parabol|integral|türev|turev|eğri|egri|koordinat|eksen)\w*\b.{0,40}\b(çiz|ciz|göster|goster|plot|grafik)\b/i,
  /\b(çiz|ciz|göster|goster|plot|grafik)\b.{0,40}\b(fonksiyon|denklem|polinom|parabol|integral|türev|turev|eğri|egri|koordinat|eksen)\w*\b/i,
  /\bf\s*\(\s*x\s*\)/i, // f(x) = ... ifadesinin grafiği
];

// Pro model SADECE açık, pahalıyı hak eden taleplerde denenir. Eski liste
// ("detaylı", "gerçekçi", "afiş", "kapak"...) neredeyse her yaratıcı istemi
// premium'a yükseltiyordu — tek görsel ~10 TL'ye çıkıyordu. Genel kelimeler
// bilinçli olarak çıkarıldı; ayrıca GEMINI_IMAGE_PRO_ENABLED flag'i kapalıyken
// (default) Pro hiç kullanılmaz.
const PREMIUM_IMAGE_REQUEST_PATTERNS = [
  /\b(en kaliteli|yüksek kalite|yuksek kalite|profesyonel|premium|ultra kalite|photorealistic|stüdyo çekimi|studyo cekimi|product shot)\b/i,
  /\b(2k|4k|high resolution|hi-res|yüksek çözünürlük|yuksek cozunurluk)\b/i,
];

const HIGH_RESOLUTION_REQUEST_PATTERN =
  /\b(2k|4k|high resolution|hi-res|yüksek çözünürlük|yuksek cozunurluk)\b/i;

/** Gemini çıktı boyutu: config değeri tavan davranır. Default tavan "1K" —
 * 2K/4K yalnızca operatör GEMINI_IMAGE_SIZE'ı yükselttiyse VE kullanıcı
 * açıkça yüksek çözünürlük istediyse kullanılır. Maliyetin ana kolu bu. */
function resolveGeminiImageSize(
  prompt: string,
  configuredMax: "1K" | "2K" | "4K",
): "1K" | "2K" | "4K" {
  if (configuredMax === "1K") {
    return "1K";
  }
  return HIGH_RESOLUTION_REQUEST_PATTERN.test(compactText(prompt).toLowerCase())
    ? configuredMax
    : "1K";
}

function compactText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readArray(record: Record<string, unknown> | null, key: string): unknown[] {
  const value = record?.[key];
  return Array.isArray(value) ? value : [];
}

function readString(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function shouldGenerateHostedImage(prompt: string): boolean {
  const normalized = compactText(prompt).toLowerCase();
  if (!normalized) {
    return false;
  }
  if (NON_CREATIVE_EXPORT_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return false;
  }
  // Veri/matematik grafiği istekleri hosted image'a ASLA gitmez — chart/math
  // pipeline'ına bırakılır (aksi halde "grafiğini çiz" stok fotoğraf üretir).
  if (DATA_VISUALIZATION_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized))) {
    return false;
  }
  return CREATIVE_IMAGE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

export function isHostedImageGenerationRequest(prompt: string): boolean {
  return shouldGenerateHostedImage(prompt);
}

function joinUrl(baseUrl: string, path: string): string {
  const normalizedBase = baseUrl.replace(/\/+$/, "");
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${normalizedBase}${normalizedPath}`.replace(/\/v1\/v1\//g, "/v1/");
}

function inferImageSize(prompt: string): "1024x1024" | "1024x1536" | "1536x1024" {
  const normalized = compactText(prompt).toLowerCase();
  if (/\b(afiş|afis|poster|flyer)\b/i.test(normalized)) {
    return "1024x1536";
  }
  if (/\b(banner|kapak|cover|thumbnail|hero)\b/i.test(normalized)) {
    return "1536x1024";
  }
  return "1024x1024";
}

function inferGeminiAspectRatio(prompt: string): "1:1" | "2:3" | "3:2" | "9:16" | "16:9" {
  const normalized = compactText(prompt).toLowerCase();
  if (/\b(afiş|afis|poster|flyer|dikey|vertical|story|reels|tiktok)\b/i.test(normalized)) {
    return "2:3";
  }
  if (/\b(telefon duvar kağıdı|telefon duvar kagidi|lock screen|story|reels|tiktok|9:16)\b/i.test(normalized)) {
    return "9:16";
  }
  if (/\b(banner|kapak|cover|thumbnail|hero|wide|yatay|landscape|16:9)\b/i.test(normalized)) {
    return "16:9";
  }
  if (/\b(3:2)\b/i.test(normalized)) {
    return "3:2";
  }
  return "1:1";
}

function shouldPreferPremiumImageModel(
  prompt: string,
  proEnabled: boolean,
): boolean {
  if (!proEnabled) {
    return false;
  }
  const normalized = compactText(prompt).toLowerCase();
  return PREMIUM_IMAGE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

function inferAttachmentSummary(metadata: Record<string, unknown> | undefined): string | null {
  const record = readRecord(metadata);
  if (!record) {
    return null;
  }

  const attachments = readArray(record, "attachments")
    .map((item) => readRecord(item))
    .filter((item): item is Record<string, unknown> => item != null);

  for (const attachment of attachments) {
    const deepContext = readRecord(attachment.deepContext);
    const fastPreview = readRecord(attachment.fastPreview);
    const deepAnalysis = readRecord(deepContext?.document_analysis);
    const summary =
      readString(fastPreview, "summary") ??
      readString(deepAnalysis, "summary") ??
      readString(attachment, "summary") ??
      readString(readRecord(attachment.document_analysis), "summary");
    if (summary) {
      return summary;
    }
  }

  return (
    readString(readRecord(record.document_analysis), "summary") ??
    readString(readRecord(record.documentAnalysis), "summary")
  );
}

function buildHostedImagePrompt(input: HostedImageArtifactInput): string {
  const attachmentSummary = inferAttachmentSummary(input.metadata);
  const sections = [
    "Create one polished production-ready image for a mobile user.",
    // "User request:" etiketiyle verilen istem, modelin istem METNİNİ görselin
    // üstüne yazmasına yol açıyordu ("kedi resmi çiz" yazılı kedi görseli).
    // İstem "çizilecek konu" olarak veriliyor ve metin çizimi açıkça yasaklanıyor.
    `Depict the following subject (this is a description of WHAT to draw, never text to render): ${compactText(input.prompt)}`,
    attachmentSummary ? `Attachment summary: ${attachmentSummary}` : null,
    compactText(input.responseText)
      ? `Approved content brief: ${compactText(input.responseText)}`
      : null,
    "CRITICAL: Do not render ANY text, words, letters, captions, labels, instructions, watermarks, signatures, or logos inside the image. The image must be completely text-free — the ONLY exception is when the user explicitly asked for specific wording (e.g. a poster title or a sign); in that case render exactly that requested text and nothing else. Never write the request itself onto the image. No UI chrome.",
  ];
  return sections.filter((value): value is string => Boolean(value)).join("\n\n");
}

function buildArtifactName(prompt: string, mimeType: string): string {
  const normalizedPrompt = compactText(prompt).toLowerCase();
  const extension = mimeType === "image/jpeg" ? "jpg" : mimeType === "image/webp" ? "webp" : "png";
  if (/\b(afiş|afis|poster)\b/i.test(normalizedPrompt)) {
    return `elyan-poster.${extension}`;
  }
  if (/\b(banner|thumbnail|kapak|cover)\b/i.test(normalizedPrompt)) {
    return `elyan-visual.${extension}`;
  }
  return `elyan-image.${extension}`;
}

/** Aynı çıktıyı belirleyen sinyallerden önbellek anahtarı üretir. Farklı
 * kullanıcıların aynı istemi (aynı oran/boyut/kalite) tek çağrıda paylaşması
 * için istem metni + oran + boyut + kalite katmanı üzerinden hash'lenir. */
function imageCacheKey(prompt: string, proEnabled: boolean, geminiSize: string): string {
  const seed = [
    compactText(prompt).toLowerCase(),
    inferGeminiAspectRatio(prompt),
    inferImageSize(prompt),
    geminiSize,
    shouldPreferPremiumImageModel(prompt, proEnabled) ? "premium" : "standard",
  ].join("|");
  const digest = createHash("sha256").update(seed).digest("hex").slice(0, 32);
  return `image:cache:v1:${digest}`;
}

async function readCachedImage(
  store: ReliabilityStore | null,
  cacheKey: string,
  prompt: string,
): Promise<HostedImageArtifactResult | null> {
  if (!store) {
    return null;
  }
  const raw = await store.get(cacheKey).catch(() => null);
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as CachedImagePayload;
    if (!parsed.base64) {
      return null;
    }
    return buildImageArtifactResult({
      prompt,
      base64: parsed.base64,
      mimeType: parsed.mimeType || "image/jpeg",
      revisedPrompt: parsed.revisedPrompt ?? null,
      model: parsed.model || "",
    });
  } catch {
    return null;
  }
}

async function writeCachedImage(
  store: ReliabilityStore | null,
  cacheKey: string,
  result: HostedImageArtifactResult,
): Promise<void> {
  if (!store) {
    return;
  }
  const base64 = Buffer.from(result.binaryBody).toString("base64");
  // Çok büyük görselleri önbelleğe alma (bellek-fallback modunda süreç
  // belleğini şişirmesin); dedup değeri küçük/orta görsellerde en yüksek.
  if (!base64 || base64.length > IMAGE_CACHE_MAX_BASE64_LENGTH) {
    return;
  }
  const payload: CachedImagePayload = {
    base64,
    mimeType: result.mimeType,
    revisedPrompt: result.revisedPrompt,
    model: result.model,
  };
  await store.set(cacheKey, JSON.stringify(payload), IMAGE_CACHE_TTL_MS).catch(() => undefined);
}

function setImageGenerationBlockReason(
  metadata: Record<string, unknown> | undefined,
  reason: string,
  details: Record<string, unknown> = {},
): void {
  if (!metadata) {
    return;
  }
  metadata.imageGenerationBlockedReason = reason;
  metadata.imageGenerationBlockedDetails = details;
}

function resolveImageRateLimitForPlan(planCode?: string | null): number {
  const normalized = String(planCode || "free").trim().toLowerCase();
  return IMAGE_RATE_LIMITS_BY_PLAN[normalized] ?? IMAGE_RATE_LIMITS_BY_PLAN.free;
}

async function consumeImageGenerationRateLimit(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
  allowance: ImageGenerationUsageAllowance | "blocked" | null,
): Promise<boolean> {
  const store = resolveReliabilityStore(app);
  if (!store) {
    return true;
  }

  const planCode =
    allowance && allowance !== "blocked" && allowance.planCode
      ? allowance.planCode
      : "free";
  const perUserLimit = resolveImageRateLimitForPlan(planCode);
  const userKey = input.userId
    ? `rate:image:user:${input.userId}:${planCode}`
    : "rate:image:user:anonymous";
  const globalKey = "rate:image:global";

  const [userCount, globalCount] = await Promise.all([
    store.increment(userKey, IMAGE_RATE_LIMIT_WINDOW_MS),
    store.increment(globalKey, IMAGE_RATE_LIMIT_GLOBAL_WINDOW_MS),
  ]);

  if (userCount > perUserLimit || globalCount > IMAGE_RATE_LIMIT_GLOBAL_MAX) {
    setImageGenerationBlockReason(input.metadata, "image_generation_rate_limited", {
      planCode,
      limit: perUserLimit,
      windowSeconds: Math.ceil(IMAGE_RATE_LIMIT_WINDOW_MS / 1000),
      retryAfterSeconds: userCount > perUserLimit ? 60 : 10,
      globalLimited: globalCount > IMAGE_RATE_LIMIT_GLOBAL_MAX,
    });
    app.log.warn(
      {
        userId: input.userId,
        planCode,
        userCount,
        userLimit: perUserLimit,
        globalCount,
        globalLimit: IMAGE_RATE_LIMIT_GLOBAL_MAX,
      },
      "hosted image generation rate limited",
    );
    return false;
  }

  return true;
}

async function assertImageGenerationPlanAllowance(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
): Promise<ImageGenerationUsageAllowance | "blocked" | null> {
  if (!input.userId || !("db" in app) || !app.db) {
    return null;
  }
  try {
    const summary = await assertMonthlyImageGenerationAllowed(app.db, input.userId);
    return {
      planCode: summary.planCode,
      limit: summary.imageGenerationUsage.limit,
      used: summary.imageGenerationUsage.used,
      remaining: summary.imageGenerationUsage.remaining,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (message === "image_generation_limit_reached") {
      const details =
        error && typeof error === "object" && "details" in error
          ? (error as { details?: unknown }).details
          : null;
      setImageGenerationBlockReason(
        input.metadata,
        "image_generation_limit_reached",
        details && typeof details === "object" && !Array.isArray(details)
          ? (details as Record<string, unknown>)
          : {},
      );
      app.log.warn(
        {
          userId: input.userId,
          reason: "image_generation_limit_reached",
        },
        "hosted image generation blocked by plan quota",
      );
      return "blocked";
    }
    throw error;
  }
}

async function recordSuccessfulImageGenerationUsage(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
  allowance: ImageGenerationUsageAllowance | "blocked" | null,
): Promise<void> {
  if (!input.userId || !("db" in app) || !app.db || allowance === "blocked") {
    return;
  }
  await recordImageGenerationUsage(app.db, {
    userId: input.userId,
    taskId: input.taskId ?? null,
    planCode:
      allowance?.planCode === "solo" || allowance?.planCode === "pro"
        ? allowance.planCode
        : "free",
    limit: allowance?.limit ?? null,
    usedBefore: allowance?.used ?? null,
  }).catch((error) => {
    app.log.warn(
      { err: error, userId: input.userId },
      "hosted image generation usage record failed",
    );
  });
}

export async function maybeGenerateHostedImageArtifact(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
): Promise<HostedImageArtifactResult | null> {
  if (!shouldGenerateHostedImage(input.prompt)) {
    return null;
  }

  const providers = buildHostedImageProviderConfigs(app, input.prompt);
  if (!providers.length) {
    return null;
  }

  const allowance = await assertImageGenerationPlanAllowance(app, input);
  if (allowance === "blocked") {
    return null;
  }

  const store = resolveReliabilityStore(app);
  const cacheKey = imageCacheKey(
    input.prompt,
    app.config.GEMINI_IMAGE_PRO_ENABLED === true,
    resolveGeminiImageSize(input.prompt, app.config.GEMINI_IMAGE_SIZE ?? "1K"),
  );

  // 1) Önbellek: aynı istem yakın zamanda üretildiyse dış çağrı yok.
  const cached = await readCachedImage(store, cacheKey, input.prompt);
  if (cached) {
    await recordSuccessfulImageGenerationUsage(app, input, allowance);
    return cached;
  }

  // 2) Single-flight: aynı istemi eşzamanlı üreten diğer istekler kilidi
  //    alamaz; kısa süre önbelleği bekler, üretici bitirince onu paylaşır.
  const lockKey = `lock:image:gen:${cacheKey}`;
  const lockOwner = `${process.pid}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
  let holdsLock = true;
  if (store) {
    holdsLock = await store
      .acquireLock(lockKey, lockOwner, IMAGE_SINGLEFLIGHT_LOCK_TTL_MS)
      .catch(() => true);
    if (!holdsLock) {
      const shared = await waitForSharedImage(store, cacheKey, input.prompt);
      if (shared) {
        await recordSuccessfulImageGenerationUsage(app, input, allowance);
        return shared;
      }
      // Kilit sahibi başarısız olmuş olabilir — yine de üretmeyi dene.
    }
  }

  const rateLimitAllowed = await consumeImageGenerationRateLimit(app, input, allowance);
  if (!rateLimitAllowed) {
    if (store && holdsLock) {
      await store.releaseLock(lockKey, lockOwner).catch(() => undefined);
    }
    return null;
  }

  // 3) Kullanıcı başına adil eşzamanlılık: bir kullanıcı tüm slotları yiyemez.
  const perUserPermit = input.userId
    ? await tryAcquireLoadSheddingPermit(app, {
        namespace: `hosted_image_user:${input.userId}`,
        maxConcurrent: IMAGE_MAX_INFLIGHT_PER_USER,
        ttlMs: IMAGE_PER_USER_TTL_MS,
        salt: `${input.userId}:${Date.now()}`,
      }).catch(() => null)
    : await tryAcquireLoadSheddingPermit(app, {
        namespace: "hosted_image_user:anonymous",
        maxConcurrent: IMAGE_GLOBAL_MAX_CONCURRENT,
        ttlMs: IMAGE_PER_USER_TTL_MS,
      }).catch(() => null);
  if (input.userId && !perUserPermit) {
    app.log.warn({ userId: input.userId }, "hosted image generation deferred: per-user cap reached");
    if (store && holdsLock) {
      await store.releaseLock(lockKey, lockOwner).catch(() => undefined);
    }
    return null;
  }

  // 4) Global eşzamanlılık: sunucu geneli tavan. Anında düşürmek yerine kısa
  //    sınırlı yeniden deneme (bursty yükte gereksiz düşüşleri azaltır).
  let globalPermit = null;
  for (let attempt = 0; attempt < IMAGE_GLOBAL_PERMIT_RETRIES && !globalPermit; attempt += 1) {
    globalPermit = await tryAcquireLoadSheddingPermit(app, {
      namespace: "hosted_image_generation",
      maxConcurrent: IMAGE_GLOBAL_MAX_CONCURRENT,
      ttlMs: IMAGE_GLOBAL_PERMIT_TTL_MS,
      salt: input.prompt.slice(0, 64),
    }).catch(() => null);
    if (!globalPermit && attempt < IMAGE_GLOBAL_PERMIT_RETRIES - 1) {
      await delay(IMAGE_GLOBAL_PERMIT_RETRY_DELAY_MS);
    }
  }
  if (!globalPermit) {
    app.log.warn("hosted image generation shed due to load");
    await perUserPermit?.release().catch(() => undefined);
    if (store && holdsLock) {
      await store.releaseLock(lockKey, lockOwner).catch(() => undefined);
    }
    return null;
  }

  try {
    const result = await generateHostedImageArtifactWithPermit(app, input, providers);
    if (result) {
      await writeCachedImage(store, cacheKey, result);
      await recordSuccessfulImageGenerationUsage(app, input, allowance);
    }
    return result;
  } finally {
    await globalPermit.release().catch(() => undefined);
    await perUserPermit?.release().catch(() => undefined);
    if (store && holdsLock) {
      await store.releaseLock(lockKey, lockOwner).catch(() => undefined);
    }
  }
}

/** Single-flight kilidi alınamadığında, üreten isteğin sonucunu kısa süre
 * önbellekten bekler. */
async function waitForSharedImage(
  store: ReliabilityStore,
  cacheKey: string,
  prompt: string,
): Promise<HostedImageArtifactResult | null> {
  const deadline = Date.now() + IMAGE_SINGLEFLIGHT_WAIT_MS;
  while (Date.now() < deadline) {
    await delay(IMAGE_SINGLEFLIGHT_POLL_MS);
    const shared = await readCachedImage(store, cacheKey, prompt);
    if (shared) {
      return shared;
    }
  }
  return null;
}

/** Üretilen görselden mobil-uyumlu artifact sonucu kurar. Sağlayıcı/model adı
 * BİLİNÇLİ olarak artifact metadata/payload'ına YAZILMAZ — kullanıcı yüzeyinden
 * hangi dış sağlayıcının kullanıldığı asla anlaşılmamalı. */
// ── Elyan filigranı (dosyaya gömülü) ─────────────────────────────────────
// Üretilen her görselin sağ üst köşesine arkaplansız Elyan logosu bir kez,
// üretim anında bake edilir (SynthID tarzı görünür işaret). Kaydet/paylaş
// dahil her kopyada kalır; render katmanında ekstra maliyet sıfır. sharp
// dinamik yüklenir ve asset/işlem hatasında orijinal görsel değişmeden döner
// (filigran asla üretimi düşürmez).
let watermarkAssetPromise: Promise<Buffer | null> | null = null;

function loadWatermarkAsset(): Promise<Buffer | null> {
  watermarkAssetPromise ??= readFile(
    path.resolve(process.cwd(), "assets/elyan-watermark.png"),
  ).catch(() => null);
  return watermarkAssetPromise;
}

async function applyElyanWatermark(
  app: FastifyInstance,
  base64: string,
  mimeType: string,
): Promise<string> {
  try {
    const [sharpModule, watermark] = await Promise.all([
      import("sharp"),
      loadWatermarkAsset(),
    ]);
    if (!watermark) {
      return base64;
    }
    const sharp = sharpModule.default;
    const source = Buffer.from(base64, "base64");
    const metadata = await sharp(source).metadata();
    const width = metadata.width ?? 0;
    const height = metadata.height ?? 0;
    if (width < 128 || height < 128) {
      return base64;
    }
    const markWidth = Math.max(48, Math.round(width * 0.075));
    const margin = Math.max(14, Math.round(width * 0.03));
    const mark = await sharp(watermark).resize(markWidth).png().toBuffer();
    const composited = sharp(source).composite([
      { input: mark, top: margin, left: width - markWidth - margin },
    ]);
    const output =
      mimeType === "image/png"
        ? await composited.png().toBuffer()
        : await composited.jpeg({ quality: 90 }).toBuffer();
    return output.toString("base64");
  } catch (error) {
    app.log.warn({ err: error }, "elyan watermark embed failed; using original image");
    return base64;
  }
}

function buildImageArtifactResult(params: {
  prompt: string;
  base64: string;
  mimeType: string;
  revisedPrompt: string | null;
  model: string;
}): HostedImageArtifactResult {
  const { prompt, base64, mimeType, revisedPrompt, model } = params;
  const previewText = "Görsel hazır.";
  return {
    artifact: {
      kind: "file",
      name: buildArtifactName(prompt, mimeType),
      contentType: mimeType,
      textContent: previewText,
      payload: {
        previewText,
        mimeType,
        revisedPrompt: revisedPrompt ?? undefined,
        source: "elyan_image_generation",
      },
      metadata: {
        sourceType: "task_artifact",
        contentFamily: "image",
        viewerHint: "image",
        mimeType,
      },
    },
    binaryBody: Buffer.from(base64, "base64"),
    mimeType,
    model,
    previewText,
    revisedPrompt,
  };
}

function buildHostedImageProviderConfigs(
  app: FastifyInstance,
  prompt: string,
): HostedImageProviderConfig[] {
  const geminiApiKey = String(app.config.GEMINI_API_KEY ?? "").trim();
  const openAiApiKey = String(app.config.OPENAI_API_KEY ?? "").trim();
  const providers: HostedImageProviderConfig[] = [];

  if (geminiApiKey) {
    const baseUrl = String(
      app.config.GEMINI_INTERACTIONS_BASE_URL ??
        "https://generativelanguage.googleapis.com/v1beta",
    ).trim();
    const fastImageModel = String(
      app.config.GEMINI_IMAGE_MODEL ?? "gemini-3.1-flash-image",
    ).trim();
    const premiumImageModel = String(
      app.config.GEMINI_IMAGE_PRO_MODEL ?? "gemini-3-pro-image-preview",
    ).trim();
    const imageSize = resolveGeminiImageSize(
      prompt,
      app.config.GEMINI_IMAGE_SIZE ?? "1K",
    );
    const addGeminiProvider = (model: string) => {
      if (
        !model ||
        providers.some((provider) => provider.provider === "gemini" && provider.model === model)
      ) {
        return;
      }
      providers.push({
        provider: "gemini",
        apiKey: geminiApiKey,
        baseUrl,
        model,
        source: "elyan_image_generation",
        imageSize,
      });
    };

    if (
      shouldPreferPremiumImageModel(
        prompt,
        app.config.GEMINI_IMAGE_PRO_ENABLED === true,
      )
    ) {
      addGeminiProvider(premiumImageModel);
      addGeminiProvider(fastImageModel);
    } else {
      addGeminiProvider(fastImageModel);
    }
  }

  if (openAiApiKey) {
    providers.push({
      provider: "openai",
      apiKey: openAiApiKey,
      baseUrl: String(app.config.OPENAI_BASE_URL ?? "https://api.openai.com/v1").trim(),
      model: "gpt-image-1",
      source: "elyan_image_generation",
    });
  }

  return providers.filter((provider) => provider.apiKey && provider.baseUrl && provider.model);
}

async function generateHostedImageArtifactWithPermit(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
  providers: HostedImageProviderConfig[],
): Promise<HostedImageArtifactResult | null> {
  const size = inferImageSize(input.prompt);
  const store = resolveReliabilityStore(app);

  for (const providerConfig of providers) {
    const circuitKey = imageCircuitKey(providerConfig.provider, providerConfig.model);
    // Devre kesici: bu sağlayıcı+model son zamanlarda çökmüşse (ör. 429
    // prepayment depleted) çağrıyı hiç yapma — timeout slotunu boşa harcamak
    // yerine anında sonraki sağlayıcıya geç.
    if (store && !(await isCircuitCallAllowed(store, circuitKey).catch(() => true))) {
      app.log.warn(
        { provider: providerConfig.provider },
        "hosted image generation skipped: provider circuit open",
      );
      continue;
    }

    try {
      const response =
        providerConfig.provider === "gemini"
          ? await fetch(joinUrl(providerConfig.baseUrl, "/interactions"), {
              method: "POST",
              headers: {
                "x-goog-api-key": providerConfig.apiKey,
                "Content-Type": "application/json",
              },
              body: JSON.stringify(buildGeminiInteractionRequestBody(providerConfig, input)),
              signal: AbortSignal.timeout(60_000),
            })
          : await fetch(joinUrl(providerConfig.baseUrl, "/images/generations"), {
              method: "POST",
              headers: {
                Authorization: `Bearer ${providerConfig.apiKey}`,
                "Content-Type": "application/json",
              },
              body: JSON.stringify(buildOpenAiImageGenerationRequestBody(providerConfig, input, size)),
              signal: AbortSignal.timeout(45_000),
            });

      if (!response.ok) {
        app.log.warn(
          {
            provider: providerConfig.provider,
            statusCode: response.status,
          },
          "hosted image generation request failed",
        );
        await recordProviderFailure(store, circuitKey, response.status);
        continue;
      }

      const payload = await response.json();
      const extractedImage = extractGeneratedImage(payload);
      const base64 = compactText(extractedImage.base64);
      if (!base64) {
        // Boş/şekilsiz gövde de bir başarısızlıktır (sağlayıcı sağlıksız).
        await recordProviderFailure(store, circuitKey, null);
        continue;
      }

      const mimeType =
        extractedImage.mimeType ??
        (providerConfig.provider === "gemini" ? "image/jpeg" : "image/png");
      const revisedPrompt = compactText(extractedImage.revisedPrompt) || null;
      if (store) {
        await recordCircuitSuccess(store, circuitKey, IMAGE_CIRCUIT_OPEN_MS).catch(() => undefined);
      }
      // Filigran üretim anında gömülür — önbellek ve kalıcı artifact de
      // işaretli kopyayı taşır.
      const watermarkedBase64 = await applyElyanWatermark(app, base64, mimeType);
      return buildImageArtifactResult({
        prompt: input.prompt,
        base64: watermarkedBase64,
        mimeType,
        revisedPrompt,
        model: providerConfig.model,
      });
    } catch (error) {
      app.log.warn(
        { err: error, provider: providerConfig.provider },
        "hosted image generation failed",
      );
      await recordProviderFailure(store, circuitKey, null);
    }
  }

  return null;
}

/** Sağlayıcı hatasını devre kesiciye işler. Kota/ödeme (429/402/403) hataları
 * kredi yüklenene kadar sürdüğünden devreyi daha uzun süre açık tutar. */
async function recordProviderFailure(
  store: ReliabilityStore | null,
  circuitKey: string,
  status: number | null,
): Promise<void> {
  if (!store) {
    return;
  }
  const failureKind = classifyProviderFailure(status);
  const openMs =
    failureKind === "quota" ? IMAGE_CIRCUIT_QUOTA_OPEN_MS : IMAGE_CIRCUIT_OPEN_MS;
  await recordCircuitFailure(
    store,
    circuitKey,
    { failureThreshold: IMAGE_CIRCUIT_FAILURE_THRESHOLD, openMs },
    failureKind === "quota" ? "image_provider_quota" : "image_provider_error",
  ).catch(() => undefined);
}

function buildGeminiInteractionRequestBody(
  providerConfig: HostedImageProviderConfig,
  input: HostedImageArtifactInput,
): Record<string, unknown> {
  return {
    model: providerConfig.model,
    input: buildHostedImagePrompt(input),
    response_format: {
      type: "image",
      mime_type: "image/jpeg",
      aspect_ratio: inferGeminiAspectRatio(input.prompt),
      image_size: providerConfig.imageSize ?? "2K",
    },
  };
}

function buildOpenAiImageGenerationRequestBody(
  providerConfig: HostedImageProviderConfig,
  input: HostedImageArtifactInput,
  size: "1024x1024" | "1024x1536" | "1536x1024",
): Record<string, unknown> {
  return {
    model: providerConfig.model,
    prompt: buildHostedImagePrompt(input),
    size,
    response_format: "b64_json",
    n: 1,
    quality: "medium",
    output_format: "png",
  };
}

function extractGeneratedImage(payload: unknown): {
  base64: string | null;
  mimeType: string | null;
  revisedPrompt: string | null;
} {
  const visited = new Set<unknown>();
  let base64: string | null = null;
  let detectedMimeType: string | null = null;
  let revisedPrompt: string | null = null;

  const visit = (value: unknown, parentKey = "") => {
    if (base64 && detectedMimeType && revisedPrompt) {
      return;
    }
    if (!value || typeof value !== "object") {
      return;
    }
    if (visited.has(value)) {
      return;
    }
    visited.add(value);

    if (Array.isArray(value)) {
      for (const item of value) {
        visit(item, parentKey);
      }
      return;
    }

    const record = value as Record<string, unknown>;
    const b64Json = record.b64_json;
    if (!base64 && typeof b64Json === "string" && b64Json.trim()) {
      base64 = b64Json.trim();
    }

    const outputImage = readRecord(record.output_image);
    const outputImageData = outputImage?.data;
    const outputImageMimeType = readImageMimeType(outputImage);
    if (!base64 && typeof outputImageData === "string" && outputImageData.trim()) {
      base64 = outputImageData.trim();
    }
    if (!detectedMimeType && outputImageMimeType) {
      detectedMimeType = outputImageMimeType;
    }

    const inlineData = readRecord(record.inline_data) ?? readRecord(record.inlineData);
    const inlineImageData = inlineData?.data;
    const inlineImageMimeType = readImageMimeType(inlineData);
    if (!base64 && typeof inlineImageData === "string" && inlineImageData.trim()) {
      base64 = inlineImageData.trim();
    }
    if (!detectedMimeType && inlineImageMimeType) {
      detectedMimeType = inlineImageMimeType;
    }

    const data = record.data;
    const mimeType = readImageMimeType(record) ?? "";
    if (!detectedMimeType && mimeType) {
      detectedMimeType = mimeType;
    }
    if (
      !base64 &&
      parentKey.toLowerCase().includes("image") &&
      typeof data === "string" &&
      data.trim()
    ) {
      base64 = data.trim();
    }
    if (!base64 && mimeType.startsWith("image/") && typeof data === "string" && data.trim()) {
      base64 = data.trim();
    }

    const revised = record.revised_prompt;
    if (!revisedPrompt && typeof revised === "string" && revised.trim()) {
      revisedPrompt = revised.trim();
    }
    const text = record.text;
    if (!revisedPrompt && typeof text === "string" && text.trim()) {
      revisedPrompt = text.trim();
    }

    for (const [key, nestedValue] of Object.entries(record)) {
      visit(nestedValue, key);
    }
  };

  visit(payload);
  return { base64, mimeType: detectedMimeType, revisedPrompt };
}

function readImageMimeType(record: Record<string, unknown> | null): string | null {
  const value =
    typeof record?.mime_type === "string"
      ? record.mime_type
      : typeof record?.mimeType === "string"
        ? record.mimeType
        : null;
  return value?.startsWith("image/") ? value : null;
}
