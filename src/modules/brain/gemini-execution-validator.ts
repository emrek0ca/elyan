import type { FastifyInstance } from "fastify";
import { z } from "zod";
import type { DesktopWorkOrder } from "../tasks/desktop-work-order.js";
import { shouldSampleGeminiUtility } from "./gemini-free-tier-guard.js";
import { callGeminiFreeStructured } from "./gemini-utility-client.js";

const validationSchema = z.object({
  valid: z.boolean(),
  missingInputs: z.array(z.string().max(160)).max(8),
  unsafeAssumptions: z.array(z.string().max(160)).max(8),
  capabilityMismatches: z.array(z.string().max(160)).max(8),
  confidence: z.number().min(0).max(1),
});

const validationJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: ["valid", "missingInputs", "unsafeAssumptions", "capabilityMismatches", "confidence"],
  properties: {
    valid: { type: "boolean" },
    missingInputs: { type: "array", maxItems: 8, items: { type: "string", maxLength: 160 } },
    unsafeAssumptions: { type: "array", maxItems: 8, items: { type: "string", maxLength: 160 } },
    capabilityMismatches: { type: "array", maxItems: 8, items: { type: "string", maxLength: 160 } },
    confidence: { type: "number", minimum: 0, maximum: 1 },
  },
};

export type GeminiExecutionValidation = z.infer<typeof validationSchema> & {
  source: "gemini_free_advisory";
};

export async function validateExecutionPlanWithGeminiFree(
  app: FastifyInstance,
  input: { userId: string; taskId: string; workOrder: DesktopWorkOrder },
): Promise<GeminiExecutionValidation | null> {
  if (input.workOrder.planPreview.privacyClass !== "public_text") return null;
  if (!shouldSampleGeminiUtility(app, `${input.taskId}:execution`)) return null;
  const result = await callGeminiFreeStructured(app, {
    feature: "execution_validate",
    userId: input.userId,
    system: "Audit this typed work order. Do not propose extra actions. Flag missing inputs, unsafe assumptions, and capability mismatches. JSON only.",
    payload: {
      goal: input.workOrder.goal,
      constraints: input.workOrder.constraints,
      requiredCapabilities: input.workOrder.requiredCapabilities,
      expectedOutputs: input.workOrder.expectedOutputs,
      verificationRules: input.workOrder.verificationRules,
      planPreview: input.workOrder.planPreview,
    },
    schema: validationSchema,
    jsonSchema: validationJsonSchema,
    sensitivity: "none",
    maxOutputTokens: 420,
    timeoutMs: 3_000,
  });
  return result ? { ...result, source: "gemini_free_advisory" } : null;
}
