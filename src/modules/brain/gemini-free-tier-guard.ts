import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { unicodeWordPattern } from "../../lib/tr-word-boundary.js";
import { buildGeminiModelCatalog } from "./gemini-models.js";

export type GeminiFreeFeature =
  | "brain_response"
  | "intent_route"
  | "attachment_analyze"
  | "execution_validate"
  | "quality_judge"
  | "web_synthesize"
  | "translate"
  | "accessibility";

export type GeminiDataSensitivity = "none" | "personal" | "sensitive" | "restricted";

export type GeminiFreeDataLineage = Partial<{
  profile: boolean;
  memory: boolean;
  worldContext: boolean;
  contextPacket: boolean;
  mcp: boolean;
  connector: boolean;
  accountData: boolean;
  toolResult: boolean;
  attachment: boolean;
  conversationHistory: boolean;
}>;

export type GeminiFreePermit = {
  allowed: boolean;
  reason:
    | "allowed"
    | "disabled"
    | "missing_key"
    | "data_usage_not_attested"
    | "model_not_allowlisted"
    | "private_data_blocked"
    | "provider_cooldown"
    | "global_request_limit"
    | "user_request_limit"
    | "feature_request_limit"
    | "input_token_limit"
    | "feature_input_token_limit"
    | "output_token_limit"
    | "feature_output_token_limit"
    | "budget_store_unavailable";
  model: string;
  estimatedInputTokens: number;
};

const FEATURE_BUDGET_SHARE: Record<GeminiFreeFeature, number> = {
  brain_response: 0.28,
  intent_route: 0.18,
  attachment_analyze: 0.12,
  execution_validate: 0.1,
  quality_judge: 0.1,
  web_synthesize: 0.1,
  translate: 0.07,
  accessibility: 0.05,
};

const GEMINI_FREE_COOLDOWN_KEY = "gemini:free:provider_cooldown";
const DEFAULT_GEMINI_FREE_COOLDOWN_MS = 120_000;
const MAX_GEMINI_FREE_COOLDOWN_MS = 15 * 60_000;

const PRIVATE_ACCOUNT_OPERATION_PATTERN = unicodeWordPattern(
  "(?:my|mine|benim|bana\\s+ait|hesabım(?:da|daki)?|hesabim(?:da|daki)?|bağlı\\s+hesabım|bagli\\s+hesabim|gelen\\s+kutum|inbox(?:ım)?|mailim|maillerim|mesajlarım|mesajlarim|takvimim|ajandam|dosyalarım|dosyalarim|repolar[ıi]m|issue(?:lar)?[ıi]m|pull\\s+requestlerim|kanallar[ıi]m|sayfalar[ıi]m|projelerim)",
  "iu",
);
const PRIVATE_ACCOUNT_DATA_PATTERN = unicodeWordPattern(
  "(?:gmail|drive|google\\s+drive|calendar|takvim|slack|notion|github|linear|mail|e-?posta|email|inbox|mesaj|message|repo|repository|issue|pull\\s+request|channel|workspace|account|hesap)",
  "iu",
);
const PRIVATE_RAW_CONTENT_PATTERN =
  new RegExp(
    `(?:[A-Z0-9._%+-]+@[A-Z0-9.-]+\\.[A-Z]{2,}|https?:\\/\\/\\S+|file:\\/\\/|\\/Users\\/|[A-Za-z]:\\\\|${unicodeWordPattern("(?:password|parola|şifre|sifre|token|secret|credential|kimlik|sağlık|saglik|adresim|telefonum|özel|ozel|private)", "iu").source})`,
    "iu",
  );
const FIRST_PERSON_PERSONAL_PATTERN = new RegExp(
  `(?:${unicodeWordPattern("(?:ben|bana|beni|benim|bende|adım|adim|ismim|yaşım|yasim|yaşıyorum|yasiyorum|konumum|evim|işim|isim|ailem|my|mine|me|myself)", "iu").source}|\\bI\\s+(?:am|have|live|work|need|want|feel)\\b)`,
  "iu",
);

function featureBudgetLimit(total: number, feature: GeminiFreeFeature): number {
  return Math.max(1, Math.floor(total * FEATURE_BUDGET_SHARE[feature]));
}

export function hasPrivateGeminiFreeDataLineage(
  lineage: GeminiFreeDataLineage | null | undefined,
): boolean {
  return Boolean(lineage && Object.values(lineage).some((value) => value === true));
}

/**
 * Returns only text that is safe to use as a public operation-classification
 * frame. Private account requests are skipped instead of trying to redact the
 * user's mailbox, calendar, MCP or connector wording heuristically.
 */
export function buildGeminiFreePublicOperationFrame(value: string): string | null {
  const compact = value.replace(/\s+/g, " ").trim().slice(0, 2_000);
  if (!compact) return null;
  if (
    PRIVATE_RAW_CONTENT_PATTERN.test(compact) ||
    FIRST_PERSON_PERSONAL_PATTERN.test(compact) ||
    (PRIVATE_ACCOUNT_OPERATION_PATTERN.test(compact) &&
      PRIVATE_ACCOUNT_DATA_PATTERN.test(compact))
  ) {
    return null;
  }
  return compact
    .replace(/\b\d{5,}\b/g, "[number]")
    .replace(/["'“”‘’][^"'“”‘’]{1,160}["'“”‘’]/g, "[quoted_text]");
}

export function isGeminiFreeResourceExhausted(
  status: number,
  payload?: unknown,
): boolean {
  if (status === 429) return true;
  const text = typeof payload === "string" ? payload : JSON.stringify(payload ?? null);
  return /RESOURCE_EXHAUSTED|quota[_ -]?exceeded|rate[_ -]?limit/iu.test(text.slice(0, 8_000));
}

export function readGeminiRetryAfterMs(headers: Headers): number | null {
  const raw = headers.get("retry-after")?.trim();
  if (!raw) return null;
  const seconds = Number(raw);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.round(seconds * 1_000);
  const at = Date.parse(raw);
  return Number.isFinite(at) ? Math.max(0, at - Date.now()) : null;
}

export async function recordGeminiFreeCooldown(
  app: FastifyInstance,
  retryAfterMs?: number | null,
): Promise<void> {
  const store = app.services?.reliability?.store;
  if (!store) return;
  const ttlMs = Math.min(
    MAX_GEMINI_FREE_COOLDOWN_MS,
    Math.max(30_000, retryAfterMs ?? DEFAULT_GEMINI_FREE_COOLDOWN_MS),
  );
  await store.set(GEMINI_FREE_COOLDOWN_KEY, "1", ttlMs);
}

function csv(value: unknown): string[] {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
}

function utcBudgetWindow(): { day: string; ttlMs: number } {
  const now = new Date();
  const next = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
  return {
    day: now.toISOString().slice(0, 10),
    ttlMs: Math.max(60_000, next - now.getTime()),
  };
}

export function estimateGeminiTokens(value: unknown): number {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? null);
  return Math.max(1, Math.ceil(Buffer.byteLength(text, "utf8") / 4));
}

function userBudgetKey(userId: string): string {
  return createHash("sha256").update(userId).digest("hex").slice(0, 24);
}

export function isGeminiFreeModelAllowed(app: FastifyInstance, model: string): boolean {
  if (app.config.GEMINI_FREE_ONLY !== true) return true;
  if (
    app.config.ELYAN_GEMINI_FREE_FEATURES_ENABLED !== true ||
    app.config.GEMINI_FREE_DATA_USAGE_ATTESTED !== true
  ) return false;
  return csv(app.config.GEMINI_FREE_MODEL_ALLOWLIST).includes(model.trim().toLowerCase());
}

export async function acquireGeminiFreePermit(
  app: FastifyInstance,
  input: {
    feature: GeminiFreeFeature;
    userId: string;
    model?: string;
    requestPayload: unknown;
    estimatedInputTokensOverride?: number;
    sensitivity?: GeminiDataSensitivity;
    userAuthorizedCloud?: boolean;
    dataLineage?: GeminiFreeDataLineage;
  },
): Promise<GeminiFreePermit> {
  // Katalog emekli adları eler; ham yapılandırma elemez.
  const model =
    String(input.model || "").trim() ||
    buildGeminiModelCatalog(app.config).fastModel;
  const estimatedInputTokens = Math.max(
    1,
    Math.trunc(
      input.estimatedInputTokensOverride ?? estimateGeminiTokens(input.requestPayload),
    ),
  );
  const denied = (reason: GeminiFreePermit["reason"]): GeminiFreePermit => ({
    allowed: false,
    reason,
    model,
    estimatedInputTokens,
  });

  if (app.config.ELYAN_GEMINI_FREE_FEATURES_ENABLED !== true) return denied("disabled");
  if (!String(app.config.GEMINI_API_KEY || "").trim()) return denied("missing_key");
  if (app.config.GEMINI_FREE_DATA_USAGE_ATTESTED !== true) {
    return denied("data_usage_not_attested");
  }
  if (!model || !isGeminiFreeModelAllowed(app, model)) return denied("model_not_allowlisted");
  const { attachment: attachmentLineage, ...nonAttachmentLineage } =
    input.dataLineage ?? {};
  if (
    hasPrivateGeminiFreeDataLineage(nonAttachmentLineage) ||
    (attachmentLineage === true && input.userAuthorizedCloud !== true) ||
    input.sensitivity === "restricted" ||
    input.sensitivity === "sensitive" ||
    (input.sensitivity === "personal" && input.userAuthorizedCloud !== true)
  ) {
    return denied("private_data_blocked");
  }

  const store = app.services?.reliability?.store;
  if (!store) return denied("budget_store_unavailable");
  const { day, ttlMs } = utcBudgetWindow();
  const userKey = userBudgetKey(input.userId);
  const prefix = `gemini:free:${day}`;
  const exhaustedKeys = {
    globalRequests: `${prefix}:requests_exhausted`,
    userRequests: `${prefix}:user:${userKey}:requests_exhausted`,
    globalInput: `${prefix}:input_exhausted`,
    featureRequests: `${prefix}:feature:${input.feature}:requests_exhausted`,
    featureInput: `${prefix}:feature:${input.feature}:input_exhausted`,
  };
  if ((await store.get(GEMINI_FREE_COOLDOWN_KEY).catch(() => "1")) === "1") {
    return denied("provider_cooldown");
  }
  if ((await store.get(`gemini:free:${day}:output_exhausted`).catch(() => "1")) === "1") {
    return denied("output_token_limit");
  }
  if (
    (await store
      .get(`gemini:free:${day}:feature:${input.feature}:output_exhausted`)
      .catch(() => "1")) === "1"
  ) {
    return denied("feature_output_token_limit");
  }
  const exhaustedValues = await Promise.all(
    Object.values(exhaustedKeys).map((key) =>
      store.get(key).catch(() => "1"),
    ),
  );
  if (exhaustedValues[0] === "1") return denied("global_request_limit");
  if (exhaustedValues[1] === "1") return denied("user_request_limit");
  if (exhaustedValues[2] === "1") return denied("input_token_limit");
  if (exhaustedValues[3] === "1") return denied("feature_request_limit");
  if (exhaustedValues[4] === "1") return denied("feature_input_token_limit");
  const [
    globalRequests,
    userRequests,
    inputTokens,
    featureRequests,
    featureInputTokens,
  ] = await Promise.all([
    store.increment(`${prefix}:requests`, ttlMs),
    store.increment(`${prefix}:user:${userKey}:requests`, ttlMs),
    store.incrementBy(`${prefix}:input_tokens`, estimatedInputTokens, ttlMs),
    store.increment(`${prefix}:feature:${input.feature}`, ttlMs),
    store.incrementBy(
      `${prefix}:feature:${input.feature}:input_tokens`,
      estimatedInputTokens,
      ttlMs,
    ),
  ]).catch(() => [
    Number.POSITIVE_INFINITY,
    Number.POSITIVE_INFINITY,
    Number.POSITIVE_INFINITY,
    Number.POSITIVE_INFINITY,
    Number.POSITIVE_INFINITY,
  ]);

  if (globalRequests > app.config.GEMINI_FREE_DAILY_REQUEST_LIMIT) {
    await store
      .set(exhaustedKeys.globalRequests, "1", ttlMs)
      .catch(() => undefined);
    return denied("global_request_limit");
  }
  if (userRequests > app.config.GEMINI_FREE_USER_DAILY_REQUEST_LIMIT) {
    await store
      .set(exhaustedKeys.userRequests, "1", ttlMs)
      .catch(() => undefined);
    return denied("user_request_limit");
  }
  if (
    featureRequests >
    featureBudgetLimit(app.config.GEMINI_FREE_DAILY_REQUEST_LIMIT, input.feature)
  ) {
    await store
      .set(exhaustedKeys.featureRequests, "1", ttlMs)
      .catch(() => undefined);
    return denied("feature_request_limit");
  }
  if (inputTokens > app.config.GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT) {
    await store
      .set(exhaustedKeys.globalInput, "1", ttlMs)
      .catch(() => undefined);
    return denied("input_token_limit");
  }
  if (
    featureInputTokens >
    featureBudgetLimit(app.config.GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT, input.feature)
  ) {
    await store
      .set(exhaustedKeys.featureInput, "1", ttlMs)
      .catch(() => undefined);
    return denied("feature_input_token_limit");
  }
  return { allowed: true, reason: "allowed", model, estimatedInputTokens };
}

export async function recordGeminiFreeOutput(
  app: FastifyInstance,
  output: unknown,
  feature?: GeminiFreeFeature,
): Promise<void> {
  const store = app.services?.reliability?.store;
  if (!store) return;
  const { day, ttlMs } = utcBudgetWindow();
  const tokens = estimateGeminiTokens(output);
  const total = await store.incrementBy(`gemini:free:${day}:output_tokens`, tokens, ttlMs);
  if (total > app.config.GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT) {
    await store.set(`gemini:free:${day}:output_exhausted`, "1", ttlMs);
  }
  if (feature) {
    const featureTotal = await store.incrementBy(
      `gemini:free:${day}:feature:${feature}:output_tokens`,
      tokens,
      ttlMs,
    );
    if (
      featureTotal >
      featureBudgetLimit(app.config.GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT, feature)
    ) {
      await store.set(
        `gemini:free:${day}:feature:${feature}:output_exhausted`,
        "1",
        ttlMs,
      );
    }
  }
}

export async function isGeminiFreeOutputBudgetAvailable(
  app: FastifyInstance,
  feature?: GeminiFreeFeature,
): Promise<boolean> {
  const store = app.services?.reliability?.store;
  if (!store) return false;
  const { day } = utcBudgetWindow();
  const keys = [
    `gemini:free:${day}:output_exhausted`,
    ...(feature
      ? [`gemini:free:${day}:feature:${feature}:output_exhausted`]
      : []),
    GEMINI_FREE_COOLDOWN_KEY,
  ];
  const values = await Promise.all(keys.map((key) => store.get(key).catch(() => "1")));
  return values.every((value) => value !== "1");
}

export function shouldSampleGeminiUtility(
  app: FastifyInstance,
  stableId: string,
): boolean {
  const percent = app.config.GEMINI_FREE_UTILITY_SAMPLE_PERCENT;
  if (percent <= 0) return false;
  if (percent >= 100) return true;
  const bucket = Number.parseInt(
    createHash("sha256").update(stableId).digest("hex").slice(0, 8),
    16,
  ) % 100;
  return bucket < percent;
}

export async function getGeminiFreeBudgetSnapshot(app: FastifyInstance) {
  const modelAllowlist = csv(app.config.GEMINI_FREE_MODEL_ALLOWLIST);
  const store = app.services?.reliability?.store;
  const { day } = utcBudgetWindow();
  const prefix = `gemini:free:${day}`;
  const readCount = async (key: string) =>
    Number.parseInt((await store?.get(key).catch(() => null)) ?? "0", 10) || 0;
  const features: GeminiFreeFeature[] = [
    "brain_response",
    "intent_route",
    "attachment_analyze",
    "execution_validate",
    "quality_judge",
    "web_synthesize",
    "translate",
    "accessibility",
  ];
  const [
    requests,
    inputTokens,
    outputTokens,
    outputExhausted,
    imageRequests,
    proImageRequests,
    fourKImageRequests,
  ] = store
    ? await Promise.all([
        readCount(`${prefix}:requests`),
        readCount(`${prefix}:input_tokens`),
        readCount(`${prefix}:output_tokens`),
        store.get(`${prefix}:output_exhausted`).catch(() => null),
        readCount(`image:daily:${day}:global`),
        readCount(`image:pro:daily:${day}:global`),
        readCount(`image:4k:daily:${day}:global`),
      ])
    : [0, 0, 0, "1", 0, 0, 0];

  return {
    enabled: app.config.ELYAN_GEMINI_FREE_FEATURES_ENABLED === true,
    freeOnly: app.config.GEMINI_FREE_ONLY === true,
    dataUsageAttested: app.config.GEMINI_FREE_DATA_USAGE_ATTESTED === true,
    ready:
      app.config.ELYAN_GEMINI_FREE_FEATURES_ENABLED === true &&
      app.config.GEMINI_FREE_DATA_USAGE_ATTESTED === true &&
      Boolean(String(app.config.GEMINI_API_KEY || "").trim()) &&
      modelAllowlist.length > 0 &&
      outputExhausted !== "1",
    modelAllowlist,
    usage: {
      day,
      requests,
      inputTokens,
      outputTokens,
      byFeature: Object.fromEntries(
        await Promise.all(
          features.map(async (feature) => [
            feature,
            await readCount(`${prefix}:feature:${feature}`),
          ]),
        ),
      ),
    },
    limits: {
      requests: app.config.GEMINI_FREE_DAILY_REQUEST_LIMIT,
      userRequests: app.config.GEMINI_FREE_USER_DAILY_REQUEST_LIMIT,
      inputTokens: app.config.GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT,
      outputTokens: app.config.GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT,
      utilitySamplePercent: app.config.GEMINI_FREE_UTILITY_SAMPLE_PERCENT,
    },
    imageCostGuard: {
      requests: imageRequests,
      requestLimit: app.config.GEMINI_IMAGE_DAILY_GLOBAL_LIMIT,
      proRequests: proImageRequests,
      proRequestLimit: app.config.GEMINI_IMAGE_PRO_DAILY_GLOBAL_LIMIT,
      fourKRequests: fourKImageRequests,
      fourKRequestLimit: app.config.GEMINI_IMAGE_4K_DAILY_GLOBAL_LIMIT,
    },
  };
}
