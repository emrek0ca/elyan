import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";

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

export type GeminiFreePermit = {
  allowed: boolean;
  reason:
    | "allowed"
    | "disabled"
    | "missing_key"
    | "data_usage_not_attested"
    | "model_not_allowlisted"
    | "private_data_blocked"
    | "global_request_limit"
    | "user_request_limit"
    | "input_token_limit"
    | "output_token_limit"
    | "budget_store_unavailable";
  model: string;
  estimatedInputTokens: number;
};

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
  },
): Promise<GeminiFreePermit> {
  const model = String(input.model || app.config.GEMINI_FAST_MODEL || "").trim();
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
  if (
    input.sensitivity === "restricted" ||
    input.sensitivity === "sensitive" ||
    (input.sensitivity === "personal" && input.userAuthorizedCloud !== true)
  ) {
    return denied("private_data_blocked");
  }

  const store = app.services?.reliability?.store;
  if (!store) return denied("budget_store_unavailable");
  const { day, ttlMs } = utcBudgetWindow();
  if ((await store.get(`gemini:free:${day}:output_exhausted`).catch(() => "1")) === "1") {
    return denied("output_token_limit");
  }
  const userKey = userBudgetKey(input.userId);
  const prefix = `gemini:free:${day}`;
  const [globalRequests, userRequests, inputTokens] = await Promise.all([
    store.increment(`${prefix}:requests`, ttlMs),
    store.increment(`${prefix}:user:${userKey}:requests`, ttlMs),
    store.incrementBy(`${prefix}:input_tokens`, estimatedInputTokens, ttlMs),
    store.increment(`${prefix}:feature:${input.feature}`, ttlMs),
  ]).catch(() => [Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY, Number.POSITIVE_INFINITY]);

  if (globalRequests > app.config.GEMINI_FREE_DAILY_REQUEST_LIMIT) {
    return denied("global_request_limit");
  }
  if (userRequests > app.config.GEMINI_FREE_USER_DAILY_REQUEST_LIMIT) {
    return denied("user_request_limit");
  }
  if (inputTokens > app.config.GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT) {
    return denied("input_token_limit");
  }
  return { allowed: true, reason: "allowed", model, estimatedInputTokens };
}

export async function recordGeminiFreeOutput(
  app: FastifyInstance,
  output: unknown,
): Promise<void> {
  const store = app.services?.reliability?.store;
  if (!store) return;
  const { day, ttlMs } = utcBudgetWindow();
  const tokens = estimateGeminiTokens(output);
  const total = await store.incrementBy(`gemini:free:${day}:output_tokens`, tokens, ttlMs);
  if (total > app.config.GEMINI_FREE_DAILY_OUTPUT_TOKEN_LIMIT) {
    await store.set(`gemini:free:${day}:output_exhausted`, "1", ttlMs);
  }
}

export async function isGeminiFreeOutputBudgetAvailable(app: FastifyInstance): Promise<boolean> {
  const store = app.services?.reliability?.store;
  if (!store) return false;
  const { day } = utcBudgetWindow();
  return (await store.get(`gemini:free:${day}:output_exhausted`).catch(() => "1")) !== "1";
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
