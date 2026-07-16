import { createHash } from "node:crypto";
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
import {
  buildHostedImageProviderRequest,
  extractHostedGeneratedImage,
  type HostedImageProviderConfig,
} from "./media/hosted-image-adapter.js";

export type HostedImageSource = {
  base64Data: string;
  mimeType: "image/jpeg" | "image/png" | "image/webp";
};

type HostedImageArtifactInput = {
  prompt: string;
  /** Legacy caller compatibility only; never forwarded to Gemini. */
  responseText?: string;
  metadata?: Record<string, unknown>;
  userId?: string;
  taskId?: string;
  sourceImages?: HostedImageSource[];
};

// ── Çoklu-kullanıcı dayanıklılık ayarları ─────────────────────────────────
// Görsel üretimi pahalı (≤60s) tek bir dış çağrı. Tek kullanıcının tüm
// kapasiteyi yemesini, bir sağlayıcı tıkandığında (ör. 429 prepayment
// depleted) her isteğin timeout slotunu boşa harcamasını ve aynı istemin
// tekrar tekrar dış sağlayıcıya gitmesini engelleyen katman.
const IMAGE_GLOBAL_MAX_CONCURRENT = 6;
const IMAGE_GLOBAL_PERMIT_TTL_MS = 180_000;
const IMAGE_GLOBAL_PERMIT_RETRIES = 3;
const IMAGE_GLOBAL_PERMIT_RETRY_DELAY_MS = 350;
// Kullanıcı başına aynı anda en fazla bu kadar üretim; aşınca metin cevabı
// yine döner ama görsel bu turda üretilmez (adil sıralama).
const IMAGE_MAX_INFLIGHT_PER_USER = 2;
const IMAGE_PER_USER_TTL_MS = 180_000;
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

// Pro model yalnız açık kalite, kimlik/ürün sadakati veya karmaşık kompozisyon
// sinyallerinde seçilir. Basit düzenlemeler Flash ile kalır.
const PREMIUM_IMAGE_REQUEST_PATTERNS = [
  /\b(en kaliteli|yüksek kalite|yuksek kalite|profesyonel|premium|ultra kalite|photorealistic|stüdyo çekimi|studyo cekimi|product shot)\b/i,
];

/** Varsayılan 2K'dır; 4K yalnız kullanıcı açıkça isterse seçilir. */
function resolveGeminiImageSize(
  prompt: string,
  configuredMax: "1K" | "2K" | "4K",
): "1K" | "2K" | "4K" {
  const normalized = compactText(prompt).toLowerCase();
  if (/\b4k\b/i.test(normalized)) return "4K";
  if (configuredMax === "1K") return "1K";
  return "2K";
}

function compactText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
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

const IMAGE_EDIT_REQUEST_PATTERNS = [
  /\b(düzenle|duzenle|değiştir|degistir|kaldır|kaldir|sil|ekle|düzelt|duzelt|iyileştir|iyilestir|netleştir|netlestir|bulanıklaştır|bulaniklastir|kırp|kirp|büyüt|buyut|küçült|kucult|retouch|edit|remove|replace|erase|add|enhance|upscale|crop|blur)\b/i,
  /\b(arka plan|rengini|stilini|ışığı|isigi|kontrastı|kontrasti)\b/i,
  /\b(bunu|görseli|gorseli|resmi|fotoğrafı|fotografi)\b.{0,60}\b(yap|çevir|cevir)\b/i,
  /\b(beni|bizi|onu|şunu|sunu|bunu|saçımı|sacimi|kıyafetimi|kiyafetimi)\b.{0,80}\b(yap|göster|goster|çevir|cevir)\b/i,
  /\b(anime|çizgi film|cizgi film|sinematik|cinematic|vintage|retro|noir|fotogerçekçi|fotogercekci|photorealistic|3d|sulu boya|watercolor|yağlı boya|yagli boya)\b.{0,50}\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b/i,
  /\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b.{0,50}\b(anime|çizgi film|cizgi film|sinematik|cinematic|vintage|retro|noir|fotogerçekçi|fotogercekci|photorealistic|3d|sulu boya|watercolor|yağlı boya|yagli boya)\b/i,
  /\b(tarzında|tarzinda|stilinde|style(?:\s+of)?|look like)\b.{0,60}\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b/i,
  /\b(yap|çevir|cevir|dönüştür|donustur|make|turn|transform)\b.{0,60}\b(tarzında|tarzinda|stilinde|style(?:\s+of)?|look like)\b/i,
  /\b(make|turn|transform)\s+(this|it|the image|the photo)\b/i,
];

export function isHostedImageEditRequest(prompt: string, sourceImageCount: number): boolean {
  if (sourceImageCount <= 0) return false;
  return isHostedImageEditIntent(prompt);
}

export function isHostedImageEditIntent(prompt: string): boolean {
  const normalized = compactText(prompt);
  return IMAGE_EDIT_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
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

function inferGeminiAspectRatio(prompt: string):
  | "1:1"
  | "2:3"
  | "3:2"
  | "3:4"
  | "4:3"
  | "4:5"
  | "5:4"
  | "9:16"
  | "16:9"
  | "21:9" {
  const normalized = compactText(prompt).toLowerCase();
  if (/\b(telefon duvar kağıdı|telefon duvar kagidi|lock screen|story|reels|tiktok|9:16)\b/i.test(normalized)) {
    return "9:16";
  }
  if (/\b(21:9|ultrawide|ultra wide|sinemaskop|cinemascope)\b/i.test(normalized)) {
    return "21:9";
  }
  if (/\b(4:5|instagram portrait|instagram dikey)\b/i.test(normalized)) {
    return "4:5";
  }
  if (/\b(5:4)\b/i.test(normalized)) {
    return "5:4";
  }
  if (/\b(3:4)\b/i.test(normalized)) {
    return "3:4";
  }
  if (/\b(4:3)\b/i.test(normalized)) {
    return "4:3";
  }
  if (/\b(banner|kapak|cover|thumbnail|hero|wide|yatay|landscape|16:9)\b/i.test(normalized)) {
    return "16:9";
  }
  if (/\b(3:2)\b/i.test(normalized)) {
    return "3:2";
  }
  if (/\b(afiş|afis|poster|flyer|dikey|vertical|2:3)\b/i.test(normalized)) {
    return "2:3";
  }
  return "1:1";
}

function shouldPreferPremiumImageModel(
  prompt: string,
  proEnabled: boolean,
): boolean {
  if (!proEnabled) return false;
  const normalized = compactText(prompt).toLowerCase();
  return PREMIUM_IMAGE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

function isSharedImageCacheEligible(prompt: string): boolean {
  const normalized = compactText(prompt);
  if (!normalized || normalized.length > 600) return false;
  return !/\b(benim|beni|bizim|bizi|ailem|çocuğum|cocugum|yüzüm|yuzum|adım|adim|adres|telefon|e-?posta|şirketim|sirketim|müşterim|musterim|özel|ozel|private|personal|my face|my family|my child|my company|my customer)\b/iu.test(
    normalized,
  );
}

function requestsPremiumImageWork(input: HostedImageArtifactInput): boolean {
  const normalized = compactText(input.prompt).toLowerCase();
  const sourceCount = input.sourceImages?.length ?? 0;
  const fidelityCritical = /\b(yüz|yuzu|yüzü|kişi|kisi|ürün|urun|marka|logo|karakter|face|person|product|brand|character)\b/iu.test(normalized)
    && /\b(aynı|ayni|koru|değiştirme|degistirme|sadık|sadik|preserve|identical|consistent|do not change)\b/iu.test(normalized);
  const personalIdentityEdit = sourceCount > 0
    && /\b(beni|bizi|yüzüm|yuzum|suratım|suratim|saçım|sacim|kıyafetim|kiyafetim|my face|my hair|my clothes)\b/iu.test(normalized)
    && IMAGE_EDIT_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
  const complexComposition = /\b(karmaşık kompozisyon|karmasik kompozisyon|çoklu sahne|coklu sahne|complex composition|multi-scene)\b/iu.test(normalized);
  return fidelityCritical || personalIdentityEdit || complexComposition
    || PREMIUM_IMAGE_REQUEST_PATTERNS.some((pattern) => pattern.test(normalized));
}

async function consumePremiumImageBudget(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
  allowance: ImageGenerationUsageAllowance | null,
): Promise<boolean> {
  if (app.config.GEMINI_IMAGE_PRO_ENABLED !== true || !requestsPremiumImageWork(input)) return false;
  if (!input.userId) return false;
  const store = resolveReliabilityStore(app);
  if (!store) return false;
  const dailyLimit = allowance?.planCode === "pro" ? 3 : allowance?.planCode === "solo" ? 1 : 0;
  if (dailyLimit <= 0) return false;
  const now = new Date();
  const nextUtcDay = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  const ttlMs = Math.max(60_000, nextUtcDay - now.getTime());
  const day = now.toISOString().slice(0, 10);
  const [globalCount, count] = await Promise.all([
    store.increment(`image:pro:daily:${day}:global`, ttlMs),
    store.increment(`image:pro:daily:${day}:${input.userId}`, ttlMs),
  ]).catch(() => [app.config.GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT + 1, dailyLimit + 1]);
  if (
    globalCount > app.config.GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT ||
    count > dailyLimit
  ) {
    app.log.warn({ userId: input.userId, dailyLimit }, "Gemini Pro image budget exhausted; using Flash");
    return false;
  }
  return true;
}

async function consumeGlobalImageDailyBudget(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
): Promise<boolean> {
  const store = resolveReliabilityStore(app);
  if (!store) {
    setImageGenerationBlockReason(input.metadata, "image_generation_budget_store_unavailable");
    return false;
  }
  const now = new Date();
  const nextUtcDay = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  const ttlMs = Math.max(60_000, nextUtcDay - now.getTime());
  const day = now.toISOString().slice(0, 10);
  const fourKRequested =
    resolveGeminiImageSize(
      input.prompt,
      app.config.GEMINI_IMAGE_SIZE ?? "2K",
    ) === "4K";
  const [count, fourKCount] = await Promise.all([
    store.increment(`image:daily:${day}:global`, ttlMs),
    fourKRequested
      ? store.increment(`image:4k:daily:${day}:global`, ttlMs)
      : Promise.resolve(0),
  ]).catch(() => [
    app.config.GEMINI_IMAGE_DAILY_GLOBAL_LIMIT + 1,
    app.config.GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT + 1,
  ]);
  if (count > app.config.GEMINI_IMAGE_DAILY_GLOBAL_LIMIT) {
    setImageGenerationBlockReason(input.metadata, "image_generation_daily_budget_exhausted", {
      limit: app.config.GEMINI_IMAGE_DAILY_GLOBAL_LIMIT,
    });
    return false;
  }
  if (
    fourKRequested &&
    fourKCount > app.config.GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT
  ) {
    setImageGenerationBlockReason(input.metadata, "image_generation_4k_budget_exhausted", {
      limit: app.config.GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT,
    });
    return false;
  }
  return true;
}

function buildHostedImagePrompt(input: HostedImageArtifactInput): string {
  return String(input.prompt ?? "").trim();
}

async function validateHostedImageOutput(base64: string): Promise<{
  base64: string;
  mimeType: "image/png" | "image/jpeg" | "image/webp";
}> {
  if (!/^[A-Za-z0-9+/]+={0,2}$/u.test(base64) || base64.length % 4 !== 0) {
    throw new Error("invalid Gemini image encoding");
  }
  const body = Buffer.from(base64, "base64");
  if (!body.byteLength || body.byteLength > 25 * 1024 * 1024) {
    throw new Error("invalid Gemini image size");
  }
  const { default: sharp } = await import("sharp");
  const metadata = await sharp(body, {
    failOn: "warning",
    limitInputPixels: 150_000_000,
  }).metadata();
  const mimeType = metadata.format === "png"
    ? "image/png"
    : metadata.format === "webp"
      ? "image/webp"
      : metadata.format === "jpeg"
        ? "image/jpeg"
        : null;
  if (!mimeType || !metadata.width || !metadata.height) {
    throw new Error("invalid Gemini image output");
  }
  return { base64: body.toString("base64"), mimeType };
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

/** Yalnız ortak cache'e uygun, kaynak görselsiz istemlerde kullanılan anahtar.
 * Kişisel sinyalli veya herhangi bir kaynak byte'ı içeren çağrı bu yola girmez. */
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
  const sourceImageCount = input.sourceImages?.length ?? 0;
  const hasSourceImages = sourceImageCount > 0;
  const editing = isHostedImageEditRequest(input.prompt, sourceImageCount);
  if (!shouldGenerateHostedImage(input.prompt) && !editing) {
    return null;
  }

  const allowance = await assertImageGenerationPlanAllowance(app, input);
  if (allowance === "blocked") {
    return null;
  }

  const store = resolveReliabilityStore(app);
  const sharedCacheAllowed =
    !hasSourceImages && isSharedImageCacheEligible(input.prompt);
  const premiumRequested = app.config.GEMINI_IMAGE_PRO_ENABLED === true && requestsPremiumImageWork(input);
  const cacheKey = imageCacheKey(
    input.prompt,
    premiumRequested,
    resolveGeminiImageSize(input.prompt, app.config.GEMINI_IMAGE_SIZE ?? "2K"),
  );

  // 1) Önbellek: aynı istem yakın zamanda üretildiyse dış çağrı yok.
  const cached = sharedCacheAllowed
    ? await readCachedImage(store, cacheKey, input.prompt)
    : null;
  if (cached) {
    await recordSuccessfulImageGenerationUsage(app, input, allowance);
    return cached;
  }
  if (!buildHostedImageProviderConfigs(app, input.prompt, false).length) {
    return null;
  }

  // 2) Single-flight: aynı istemi eşzamanlı üreten diğer istekler kilidi
  //    alamaz; kısa süre önbelleği bekler, üretici bitirince onu paylaşır.
  const lockKey = `lock:image:gen:${cacheKey}`;
  const lockOwner = `${process.pid}:${Date.now()}:${Math.random().toString(36).slice(2)}`;
  let holdsLock = true;
  if (store && sharedCacheAllowed) {
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
    if (store && holdsLock && sharedCacheAllowed) {
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
    if (store && holdsLock && sharedCacheAllowed) {
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
    if (store && holdsLock && sharedCacheAllowed) {
      await store.releaseLock(lockKey, lockOwner).catch(() => undefined);
    }
    return null;
  }

  try {
    const dailyBudgetAllowed = await consumeGlobalImageDailyBudget(app, input);
    if (!dailyBudgetAllowed) return null;

    // Pro kotasını yalnız istek bütün rate, günlük bütçe ve eşzamanlılık
    // kapılarından geçtikten sonra tüket.
    const usePremium = await consumePremiumImageBudget(
      app,
      input,
      allowance,
    );
    const providers = buildHostedImageProviderConfigs(app, input.prompt, usePremium);
    if (!providers.length) return null;
    const result = await generateHostedImageArtifactWithPermit(app, input, providers);
    if (result) {
      const premiumModel = String(
        app.config.GEMINI_IMAGE_PRO_MODEL ?? "gemini-3-pro-image",
      ).trim();
      const cacheMatchesRequestedTier =
        !premiumRequested ||
        (usePremium && result.model === premiumModel);
      if (sharedCacheAllowed && cacheMatchesRequestedTier) {
        await writeCachedImage(store, cacheKey, result);
      }
      await recordSuccessfulImageGenerationUsage(app, input, allowance);
    }
    return result;
  } finally {
    await globalPermit.release().catch(() => undefined);
    await perUserPermit?.release().catch(() => undefined);
    if (store && holdsLock && sharedCacheAllowed) {
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
  usePremium: boolean,
): HostedImageProviderConfig[] {
  const geminiApiKey = String(app.config.GEMINI_API_KEY ?? "").trim();
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
      app.config.GEMINI_IMAGE_PRO_MODEL ?? "gemini-3-pro-image",
    ).trim();
    const imageSize = resolveGeminiImageSize(
      prompt,
      app.config.GEMINI_IMAGE_SIZE ?? "2K",
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

    if (usePremium) {
      addGeminiProvider(premiumImageModel);
      addGeminiProvider(fastImageModel);
    } else {
      addGeminiProvider(fastImageModel);
    }
  }

  return providers.filter((provider) => provider.apiKey && provider.baseUrl && provider.model);
}

async function generateHostedImageArtifactWithPermit(
  app: FastifyInstance,
  input: HostedImageArtifactInput,
  providers: HostedImageProviderConfig[],
): Promise<HostedImageArtifactResult | null> {
  const store = resolveReliabilityStore(app);
  const editing = (input.sourceImages?.length ?? 0) > 0;

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
      const request = buildHostedImageProviderRequest({
        config: providerConfig,
        prompt: buildHostedImagePrompt(input),
        aspectRatio: editing ? undefined : inferGeminiAspectRatio(input.prompt),
        sourceImages: input.sourceImages,
      });
      const response = await fetch(joinUrl(providerConfig.baseUrl, request.path), {
        method: "POST",
        headers: request.headers,
        body: JSON.stringify(request.body),
        signal: AbortSignal.timeout(request.timeoutMs),
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
      const extractedImage = extractHostedGeneratedImage(payload);
      const base64 = compactText(extractedImage.base64);
      if (!base64) {
        // Boş/şekilsiz gövde de bir başarısızlıktır (sağlayıcı sağlıksız).
        await recordProviderFailure(store, circuitKey, null);
        continue;
      }

      const validatedImage = await validateHostedImageOutput(base64);
      const mimeType = validatedImage.mimeType;
      const revisedPrompt = compactText(extractedImage.revisedPrompt) || null;
      if (store) {
        await recordCircuitSuccess(store, circuitKey, IMAGE_CIRCUIT_OPEN_MS).catch(() => undefined);
      }
      return buildImageArtifactResult({
        prompt: input.prompt,
        base64: validatedImage.base64,
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
