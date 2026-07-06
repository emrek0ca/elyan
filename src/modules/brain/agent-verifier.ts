import { createHash } from "node:crypto";
import type { AgentVerification } from "./agent-plan.js";
import { agentVerificationSchema, type AgentPlanEnvelope } from "./agent-plan.js";

export type AgentEvidenceInput = {
  id?: string;
  kind: "tool_result" | "artifact" | "state_readback";
  sourceRef?: string | null;
  contentHash?: string | null;
  payload: Record<string, unknown>;
  valid?: boolean;
};

function readPath(value: unknown, path: string): unknown {
  if (!path) return value;
  return path.split(".").reduce<unknown>((current, key) => {
    if (!current || typeof current !== "object" || Array.isArray(current)) return undefined;
    return (current as Record<string, unknown>)[key];
  }, value);
}

function stableHash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function compare(operator: string, actual: unknown, expected: unknown): boolean {
  if (operator === "exists") return actual !== undefined && actual !== null;
  if (operator === "non_empty") {
    if (typeof actual === "string" || Array.isArray(actual)) return actual.length > 0;
    return Boolean(actual && typeof actual === "object" && Object.keys(actual).length > 0);
  }
  if (operator === "equals") return JSON.stringify(actual) === JSON.stringify(expected);
  if (operator === "not_equals") return JSON.stringify(actual) !== JSON.stringify(expected);
  if (operator === "gte") return typeof actual === "number" && typeof expected === "number" && actual >= expected;
  if (operator === "lte") return typeof actual === "number" && typeof expected === "number" && actual <= expected;
  if (operator === "sha256") return typeof expected === "string" && stableHash(actual) === expected;
  return false;
}

export function verifyAgentStep(input: {
  step: AgentPlanEnvelope["steps"][number];
  evidence: AgentEvidenceInput[];
}): AgentVerification {
  const validEvidence = input.evidence.filter((item) => item.valid !== false);
  const failedRules: string[] = [];
  const missingEvidence: string[] = [];
  const evidenceIds = new Set<string>();

  input.step.expected_outcome.rules.forEach((rule, index) => {
    const candidates = validEvidence.filter((item) => item.kind === rule.source);
    if (candidates.length === 0) {
      missingEvidence.push(`${rule.source}:${rule.path || "root"}`);
      return;
    }
    const passed = candidates.some((item) => {
      const actual = rule.operator === "sha256" && !rule.path
        ? item.contentHash
        : readPath(item.payload, rule.path);
      const matched = rule.operator === "sha256" && !rule.path
        ? actual === rule.value
        : compare(rule.operator, actual, rule.value);
      if (matched && item.id) evidenceIds.add(item.id);
      return matched;
    });
    if (!passed) failedRules.push(`rule_${index + 1}:${rule.source}:${rule.path || "root"}:${rule.operator}`);
  });

  const checked = input.step.expected_outcome.rules.length;
  const passed = checked > 0 && failedRules.length === 0 && missingEvidence.length === 0;
  return agentVerificationSchema.parse({
    passed,
    confidence: checked === 0 ? 0 : Math.max(0, (checked - failedRules.length - missingEvidence.length) / checked),
    checked_rules: checked,
    evidence_ids: [...evidenceIds],
    missing_evidence: missingEvidence,
    failed_rules: failedRules,
  });
}

export function canCompleteAgentRun(verifications: AgentVerification[]): boolean {
  return verifications.length > 0 && verifications.every((verification) => verification.passed);
}
