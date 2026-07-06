import { createHash } from "node:crypto";
import { z } from "zod";
import { getAgentToolMetadata, type AgentToolRequest } from "./tool-registry.js";

export const agentRunStateSchema = z.enum([
  "understanding", "planning", "ready", "executing", "observing", "verifying",
  "waiting_approval", "waiting_evidence", "replanning", "completed", "blocked",
  "failed", "canceled",
]);
export type AgentRunState = z.infer<typeof agentRunStateSchema>;

export const agentStepStateSchema = z.enum([
  "pending", "ready", "executing", "observed", "verified", "waiting_approval",
  "waiting_evidence", "failed", "skipped", "canceled",
]);
export type AgentStepState = z.infer<typeof agentStepStateSchema>;

export const verificationRuleSchema = z.object({
  source: z.enum(["tool_result", "artifact", "state_readback"]),
  path: z.string().trim().max(240).default(""),
  operator: z.enum(["exists", "equals", "not_equals", "non_empty", "gte", "lte", "sha256"]),
  value: z.unknown().optional(),
});

export const agentPlanStepSchema = z.object({
  id: z.string().trim().regex(/^[a-zA-Z0-9_-]{1,80}$/),
  title: z.string().trim().min(1).max(200),
  depends_on: z.array(z.string().trim().min(1).max(80)).max(7).default([]),
  tool_request: z.object({
    tool: z.string().trim().min(1).max(120),
    args: z.record(z.string(), z.unknown()).default({}),
  }),
  expected_outcome: z.object({
    description: z.string().trim().min(1).max(500),
    rules: z.array(verificationRuleSchema).min(1).max(8),
  }),
  max_attempts: z.number().int().min(1).max(3).default(3),
});

export const agentPlanEnvelopeSchema = z.object({
  version: z.literal("agent_plan.v2"),
  goal: z.object({
    title: z.string().trim().min(1).max(200),
    success_criteria: z.array(z.string().trim().min(1).max(500)).min(1).max(8),
  }),
  steps: z.array(agentPlanStepSchema).min(1).max(8),
}).superRefine((plan, ctx) => {
  const ids = new Set(plan.steps.map((step) => step.id));
  if (ids.size !== plan.steps.length) {
    ctx.addIssue({ code: z.ZodIssueCode.custom, path: ["steps"], message: "step ids must be unique" });
  }
  const seen = new Set<string>();
  plan.steps.forEach((step, index) => {
    for (const dependency of step.depends_on) {
      if (!ids.has(dependency) || !seen.has(dependency) || dependency === step.id) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["steps", index, "depends_on"],
          message: "dependencies must reference an earlier step",
        });
      }
    }
    seen.add(step.id);
  });
});

export type AgentPlanEnvelope = z.output<typeof agentPlanEnvelopeSchema>;

export const agentVerificationSchema = z.object({
  passed: z.boolean(),
  confidence: z.number().min(0).max(1),
  checked_rules: z.number().int().nonnegative(),
  evidence_ids: z.array(z.string().uuid()).default([]),
  missing_evidence: z.array(z.string().max(240)).max(16).default([]),
  failed_rules: z.array(z.string().max(240)).max(16).default([]),
});
export type AgentVerification = z.output<typeof agentVerificationSchema>;

export function buildAgentPlanFromToolRequests(input: {
  goal: string;
  requests: AgentToolRequest[];
}): AgentPlanEnvelope {
  return agentPlanEnvelopeSchema.parse({
    version: "agent_plan.v2",
    goal: {
      title: input.goal.slice(0, 200) || "Complete task",
      success_criteria: ["Every planned step has deterministic verification evidence."],
    },
    steps: input.requests.slice(0, 8).map((request, index) => ({
      id: `step_${index + 1}`,
      title: `Execute ${request.tool}`,
      depends_on: [],
      tool_request: request,
      expected_outcome: {
        description: `${request.tool} returns a schema-valid successful result`,
        rules: [{ source: "tool_result", path: "ok", operator: "equals", value: true }],
      },
      max_attempts: 3,
    })),
  });
}

export function hardenAgentPlanVerification(plan: AgentPlanEnvelope): AgentPlanEnvelope {
  return agentPlanEnvelopeSchema.parse({
    ...plan,
    steps: plan.steps.map((step) => {
      const suppliedRules = [...step.expected_outcome.rules];
      const rules = [] as typeof suppliedRules;
      const hasSuccessRule = suppliedRules.some((rule) =>
        rule.source === "tool_result" && rule.path === "ok" && rule.operator === "equals" && rule.value === true,
      );
      rules.push(hasSuccessRule
        ? suppliedRules.find((rule) => rule.source === "tool_result" && rule.path === "ok" && rule.operator === "equals" && rule.value === true)!
        : { source: "tool_result", path: "ok", operator: "equals", value: true });
      const metadata = getAgentToolMetadata(step.tool_request.tool);
      const needsMutationEvidence = metadata?.permission === "write" || metadata?.permission === "side_effect";
      const mutationRule = suppliedRules.find((rule) => rule.source === "state_readback" || rule.source === "artifact");
      if (needsMutationEvidence) {
        rules.push(mutationRule ?? { source: "state_readback", path: "", operator: "non_empty" });
      }
      rules.push(...suppliedRules.filter((rule) => !rules.includes(rule)));
      return {
        ...step,
        expected_outcome: { ...step.expected_outcome, rules: rules.slice(0, 8) },
      };
    }),
  });
}

export function agentStepIdempotencyKey(runId: string, stepKey: string): string {
  return createHash("sha256").update(`${runId}:${stepKey}`).digest("hex");
}
