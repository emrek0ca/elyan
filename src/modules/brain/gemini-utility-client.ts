import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { joinProviderUrl, postJson } from "./provider-http.js";
import { extractResponseText } from "./provider-response.js";
import {
  acquireGeminiFreePermit,
  isGeminiFreeOutputBudgetAvailable,
  recordGeminiFreeOutput,
  type GeminiDataSensitivity,
  type GeminiFreeFeature,
} from "./gemini-free-tier-guard.js";

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
    maxOutputTokens?: number;
    timeoutMs?: number;
    images?: Array<{ base64Data: string; mimeType: "image/png" | "image/jpeg" | "image/webp" }>;
  },
): Promise<T | null> {
  const model = String(app.config.GEMINI_FAST_MODEL || "").trim();
  if (!(await isGeminiFreeOutputBudgetAvailable(app))) return null;
  const userContent: unknown = input.images?.length
    ? [
        { type: "text", text: JSON.stringify(input.payload) },
        ...input.images.map((image) => ({
          type: "image_url",
          image_url: { url: `data:${image.mimeType};base64,${image.base64Data}`, detail: "high" },
        })),
      ]
    : JSON.stringify(input.payload);
  const requestBody = {
    model,
    temperature: 0,
    max_tokens: Math.min(1_200, Math.max(120, input.maxOutputTokens ?? 600)),
    messages: [
      { role: "system", content: input.system },
      { role: "user", content: userContent },
    ],
    response_format: {
      type: "json_schema",
      json_schema: { name: `elyan_${input.feature}`, strict: true, schema: input.jsonSchema },
    },
  };
  const permit = await acquireGeminiFreePermit(app, {
    feature: input.feature,
    userId: input.userId,
    model,
    requestPayload: requestBody,
    sensitivity: input.sensitivity,
    userAuthorizedCloud: input.userAuthorizedCloud,
  });
  if (!permit.allowed) {
    app.log.debug?.({ feature: input.feature, reason: permit.reason }, "Gemini free utility skipped");
    return null;
  }

  const response = await postJson(
    app,
    "gemini",
    joinProviderUrl(app.config.GEMINI_BASE_URL, "/chat/completions"),
    requestBody,
    Math.min(8_000, Math.max(1_000, input.timeoutMs ?? 5_000)),
  ).catch(() => null);
  if (!response?.ok) return null;
  const providerPayload = await response.json().catch(() => null);
  const parsed = input.schema.safeParse(extractJson(extractResponseText("gemini", providerPayload)));
  if (!parsed.success) return null;
  await recordGeminiFreeOutput(app, parsed.data).catch(() => undefined);
  return parsed.data;
}
