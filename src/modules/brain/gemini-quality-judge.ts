import type { FastifyInstance } from "fastify";
import { z } from "zod";
import {
  buildGeminiFreePublicOperationFrame,
  hasPrivateGeminiFreeDataLineage,
  shouldSampleGeminiUtility,
  type GeminiFreeDataLineage,
} from "./gemini-free-tier-guard.js";
import { callGeminiFreeStructured } from "./gemini-utility-client.js";

const judgeSchema = z.object({
  requestAlignment: z.number().min(0).max(1),
  completeness: z.number().min(0).max(1),
  unsupportedClaimRisk: z.number().min(0).max(1),
  needsCorrection: z.boolean(),
  reasonCodes: z.array(z.enum([
    "missing_requirement", "unsupported_claim", "wrong_format", "too_verbose",
    "too_brief", "unsafe_instruction", "none",
  ])).max(6),
});

const judgeJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["requestAlignment", "completeness", "unsupportedClaimRisk", "needsCorrection", "reasonCodes"],
  properties: {
    requestAlignment: { type: "number", minimum: 0, maximum: 1 },
    completeness: { type: "number", minimum: 0, maximum: 1 },
    unsupportedClaimRisk: { type: "number", minimum: 0, maximum: 1 },
    needsCorrection: { type: "boolean" },
    reasonCodes: {
      type: "array", maxItems: 6,
      items: { type: "string", enum: ["missing_requirement", "unsupported_claim", "wrong_format", "too_verbose", "too_brief", "unsafe_instruction", "none"] },
    },
  },
};

export async function judgeResponseWithGeminiFree(
  app: FastifyInstance,
  input: {
    userId: string;
    stableId: string;
    request: string;
    response: string;
    dataLineage?: GeminiFreeDataLineage;
  },
) {
  if (!shouldSampleGeminiUtility(app, `${input.stableId}:quality`)) return null;
  if (input.request.length > 2_000 || input.response.length < 80 || input.response.length > 6_000) return null;
  if (hasPrivateGeminiFreeDataLineage(input.dataLineage)) return null;
  const publicRequest = buildGeminiFreePublicOperationFrame(input.request);
  const publicResponse = buildGeminiFreePublicOperationFrame(input.response);
  if (!publicRequest || !publicResponse) return null;
  return callGeminiFreeStructured(app, {
    feature: "quality_judge",
    userId: input.userId,
    system: "Score request alignment and answer quality. Do not rewrite the answer. Return bounded JSON only.",
    payload: { userRequest: publicRequest, assistantResponse: publicResponse },
    schema: judgeSchema,
    jsonSchema: judgeJsonSchema,
    sensitivity: "none",
    dataLineage: input.dataLineage,
    maxOutputTokens: 220,
    timeoutMs: 2_500,
  });
}
