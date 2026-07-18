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

function structuralIdentifier(value: unknown): string | null {
  const normalized = String(value ?? "")
    .trim()
    .toLocaleLowerCase("en-US");
  return /^[a-z0-9._-]{1,64}$/.test(normalized) ? normalized : null;
}

function structuralIdentifiers(values: unknown[]): string[] {
  return [...new Set(values.map(structuralIdentifier).filter((value): value is string => Boolean(value)))]
    .slice(0, 32);
}

function buildContentlessPlanShape(workOrder: DesktopWorkOrder) {
  const requiredCapabilities = structuralIdentifiers(workOrder.requiredCapabilities);
  const steps = workOrder.planPreview.steps.slice(0, 16).map((step) => ({
    capability: structuralIdentifier(step.capability) ?? "unknown",
    argKeys: structuralIdentifiers(Object.keys(step.args)),
    hasDescription: Boolean(step.description.trim()),
  }));
  return {
    schema: workOrder.schema,
    source: workOrder.source,
    goal: {
      kind: structuralIdentifier(workOrder.goal.kind) ?? "unknown",
      language: workOrder.goal.language,
      sourceTextHashPresent: Boolean(workOrder.goal.sourceTextHash),
    },
    privacyClass: workOrder.planPreview.privacyClass,
    requiredCapabilities,
    localContextKinds: structuralIdentifiers(workOrder.localContextNeeded),
    expectedOutputs: workOrder.expectedOutputs.slice(0, 16).map((output) => ({
      kind: output.kind,
      required: output.required,
      formatPresent: Boolean(output.format.trim()),
    })),
    verificationEvidence: structuralIdentifiers(
      workOrder.verificationRules.map((rule) => rule.evidence),
    ),
    execution: workOrder.execution,
    steps,
    counts: {
      steps: workOrder.planPreview.steps.length,
      entities: workOrder.entities.length,
      constraints: workOrder.constraints.length,
      verificationRules: workOrder.verificationRules.length,
      ambiguities: workOrder.understanding?.ambiguities.length ?? 0,
    },
    risk: workOrder.understanding
      ? {
          privacy: workOrder.understanding.risk.privacy,
          safety: workOrder.understanding.risk.safety,
          cost: workOrder.understanding.risk.cost,
          latency: workOrder.understanding.risk.latency,
          localPrivate: workOrder.understanding.risk.local_private,
          sideEffect: workOrder.understanding.risk.side_effect,
          promptInjection: workOrder.understanding.risk.prompt_injection,
        }
      : null,
  };
}

export async function validateExecutionPlanWithGeminiFree(
  app: FastifyInstance,
  input: { userId: string; taskId: string; workOrder: DesktopWorkOrder },
): Promise<GeminiExecutionValidation | null> {
  const requiredCapabilities = structuralIdentifiers(input.workOrder.requiredCapabilities);
  const isMcpPlan =
    structuralIdentifier(input.workOrder.goal.kind) === "remote_mcp" ||
    requiredCapabilities.includes("mcp_call_tool");
  if (
    input.workOrder.planPreview.privacyClass !== "public_text" &&
    !(isMcpPlan && input.workOrder.planPreview.privacyClass === "local_private")
  ) return null;
  if (!shouldSampleGeminiUtility(app, `${input.taskId}:execution`)) return null;
  const result = await callGeminiFreeStructured(app, {
    feature: "execution_validate",
    userId: input.userId,
    system: "Audit only this contentless structural plan descriptor. Never infer missing user content, account data, tool arguments, or task meaning. Check shape consistency, required capability coverage, permission-risk alignment, and verification coverage. Do not propose extra actions. JSON only.",
    payload: {
      planShape: buildContentlessPlanShape(input.workOrder),
    },
    schema: validationSchema,
    jsonSchema: validationJsonSchema,
    sensitivity: "none",
    maxOutputTokens: 420,
    timeoutMs: 3_000,
  });
  return result ? { ...result, source: "gemini_free_advisory" } : null;
}
