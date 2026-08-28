import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { joinProviderUrl, postJson } from "./provider-http.js";
import { extractResponseText } from "./provider-response.js";
import {
  acquireGeminiFreePermit,
  isGeminiFreeResourceExhausted,
  isGeminiFreeOutputBudgetAvailable,
  readGeminiRetryAfterMs,
  recordGeminiFreeCooldown,
  recordGeminiFreeOutput,
  type GeminiDataSensitivity,
  type GeminiFreeDataLineage,
  type GeminiFreeFeature,
} from "./gemini-free-tier-guard.js";
import {
  buildRequestBody,
  getNativeChatPath,
  type SharedBrainConversationMessage,
} from "./provider-request.js";
import { buildGeminiModelCatalog } from "./gemini-models.js";

function extractJson(text: string): unknown | null {
  const trimmed = text.trim();
  const candidates = [
    trimmed,
    trimmed.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, ""),
  ];
  const start = trimmed.indexOf("{");
  const end = trimmed.lastIndexOf("}");
  if (start >= 0 && end > start) candidates.push(trimmed.slice(start, end + 1));
  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch {
      // Keep the utility fail-open; deterministic Elyan logic remains primary.
    }
  }
  return null;
}

/**
 * FAIL-OPEN SESSİZ OLMAMALI.
 *
 * Bu fonksiyon yedi ayrı sebeple `null` dönüyor ve hepsi aynı görünüyordu.
 * Üstündeki çağıranlar (eylem-iddia kapısı gibi) o `null`ı "semantik yok"
 * diye yorumlayıp KENDİLERİNİ devre dışı bırakıyor — ama neden devre dışı
 * kaldıklarını kimse göremiyordu. Canlıda bunun bedeli ölçüldü: emekli bir
 * modele işaret eden yapılandırma yüzünden kapı aylarca kapalıydı ve tek bir
 * uyarı düşmedi (2026-08-22 yorumu).
 *
 * Bu sarmalayıcı davranışı DEĞİŞTİRMEZ; yalnız sebebi kaydeder.
 */
function geminiUtilityUnavailable(
  app: FastifyInstance,
  feature: string,
  reason: string,
  detail?: unknown,
): null {
  app.log?.warn?.(
    { utility: "gemini_free", feature, reason, ...(detail ? { detail } : {}) },
    "gemini utility call unavailable",
  );
  return null;
}

export async function callGeminiFreeStructured<T>(
  app: FastifyInstance,
  input: {
    feature: GeminiFreeFeature;
    userId: string;
    system: string;
    payload: unknown;
    schema: z.ZodType<T>;
    jsonSchema: Record<string, unknown>;
    sensitivity?: GeminiDataSensitivity;
    userAuthorizedCloud?: boolean;
    dataLineage?: GeminiFreeDataLineage;
    maxOutputTokens?: number;
    timeoutMs?: number;
    images?: Array<{ base64Data: string; mimeType: "image/png" | "image/jpeg" | "image/webp" }>;
  },
): Promise<T | null> {
  // MODEL KATALOGDAN OKUNUR, HAM YAPILANDIRMADAN DEĞİL.
  //
  // Emekli adları eleyen kapı `buildGeminiModelCatalog` içinde; burası
  // `app.config`i doğrudan okuduğu için o kapıyı atlıyordu ve
  // `gemini-2.5-flash-lite` (politikanın `retired` listesinde, sağlayıcıda
  // 404) buradan geçmeye devam ediyordu.
  const model = buildGeminiModelCatalog(app.config).fastModel;
  if (!(await isGeminiFreeOutputBudgetAvailable(app, input.feature))) {
    return geminiUtilityUnavailable(app, input.feature, "output_budget_exhausted");
  }
  const maxOutputTokens = Math.min(1_200, Math.max(120, input.maxOutputTokens ?? 600));
  const messages: SharedBrainConversationMessage[] = [
    { role: "system", content: input.system },
    { role: "user", content: JSON.stringify(input.payload) },
  ];
  const nativeImages = (input.images ?? []).map((image, index) => ({
    documentId: `gemini-utility-${index + 1}`,
    label: `utility-image-${index + 1}`,
    mimeType: image.mimeType,
    base64: image.base64Data,
    detail: "high" as const,
  }));
  const userContent: unknown = input.images?.length
    ? [
        { type: "text", text: JSON.stringify(input.payload) },
        ...input.images.map((image) => ({
          type: "image_url",
          image_url: { url: `data:${image.mimeType};base64,${image.base64Data}`, detail: "high" },
        })),
      ]
    : JSON.stringify(input.payload);
  const compatibilityBody = {
    model,
    temperature: 0,
    max_tokens: maxOutputTokens,
    messages: [
      { role: "system", content: input.system },
      { role: "user", content: userContent },
    ],
    response_format: {
      type: "json_schema",
      json_schema: { name: `elyan_${input.feature}`, strict: true, schema: input.jsonSchema },
    },
  };
  const nativeBody = buildRequestBody(
    "gemini",
    model,
    messages,
    maxOutputTokens,
    undefined,
    false,
    nativeImages,
    "hidden",
    "low",
    0,
    input.jsonSchema,
    false,
    true,
  );
  const nativeBaseUrl = (
    String(app.config.GEMINI_INTERACTIONS_BASE_URL ?? "").trim() ||
    String(app.config.GEMINI_BASE_URL ?? "").trim().replace(/\/openai\/?$/i, "")
  ).replace(/\/+$/, "");
  const compatibilityBaseUrl = String(app.config.GEMINI_BASE_URL ?? "")
    .trim()
    .replace(/\/+$/, "");
  const permit = await acquireGeminiFreePermit(app, {
    feature: input.feature,
    userId: input.userId,
    model,
    requestPayload: nativeBody,
    sensitivity: input.sensitivity,
    userAuthorizedCloud: input.userAuthorizedCloud,
    dataLineage: {
      ...input.dataLineage,
      ...(input.images?.length ? { attachment: true } : {}),
    },
  });
  if (!permit.allowed) {
    // BU SATIR `debug` SEVİYESİNDEYDİ ve sunucu `info` ile çalışıyor — yani
    // görünmezdi. Eylem-iddia kapısının neden kapalı olduğunu araştırırken
    // diğer altı çıkışı görünür yaptım ama sayaç sıfır kaldı; sebep buydu.
    // Bir arıza, yalnız kimsenin açmadığı bir seviyede yazılıyorsa
    // kaydedilmemiş sayılır.
    return geminiUtilityUnavailable(
      app,
      input.feature,
      "permit_denied_primary",
      permit.reason ?? null,
    );
  }

  let response = await postJson(
    app,
    "gemini",
    joinProviderUrl(nativeBaseUrl, getNativeChatPath("gemini")),
    nativeBody,
    Math.min(8_000, Math.max(1_000, input.timeoutMs ?? 5_000)),
  ).catch(() => null);
  if (
    (!response || !response.ok) &&
    compatibilityBaseUrl &&
    (!response || [400, 404, 405, 415, 422].includes(response.status))
  ) {
    const compatibilityPermit = await acquireGeminiFreePermit(app, {
      feature: input.feature,
      userId: input.userId,
      model,
      requestPayload: compatibilityBody,
      sensitivity: input.sensitivity,
      userAuthorizedCloud: input.userAuthorizedCloud,
      dataLineage: {
        ...input.dataLineage,
        ...(input.images?.length ? { attachment: true } : {}),
      },
    });
    if (!compatibilityPermit.allowed) {
      return geminiUtilityUnavailable(app, input.feature, "permit_denied", compatibilityPermit.reason ?? null);
    }
    response = await postJson(
      app,
      "gemini",
      joinProviderUrl(compatibilityBaseUrl, "/chat/completions"),
      compatibilityBody,
      Math.min(8_000, Math.max(1_000, input.timeoutMs ?? 5_000)),
    ).catch(() => null);
  }
  if (!response) {
    return geminiUtilityUnavailable(app, input.feature, "no_response");
  }
  const providerPayload = await response.json().catch(() => null);
  if (!response.ok) {
    if (isGeminiFreeResourceExhausted(response.status, providerPayload)) {
      await recordGeminiFreeCooldown(
        app,
        readGeminiRetryAfterMs(response.headers),
      ).catch(() => undefined);
    }
    return geminiUtilityUnavailable(app, input.feature, "http_" + response.status);
  }
  const responseText = extractResponseText("gemini", providerPayload);
  // Count every successful provider response, including malformed JSON, so a
  // parse failure cannot consume free-tier output outside the local budget.
  await recordGeminiFreeOutput(app, responseText, input.feature).catch(
    () => undefined,
  );
  const parsed = input.schema.safeParse(extractJson(responseText));
  if (!parsed.success) {
    return geminiUtilityUnavailable(app, input.feature, "schema_mismatch");
  }
  return parsed.data;
}
