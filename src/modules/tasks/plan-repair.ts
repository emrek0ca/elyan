import { extractFirstJsonObject } from "../brain/desktop-plan.js";
import { asRecord } from "../../lib/record.js";

export function materializedPlanParseDiagnostics(
  rawPlan: Record<string, unknown> | null,
): {
  rawStepCount: number;
  invalidStepCount: number;
  invalidArgsCount: number;
} {
  const rawSteps = Array.isArray(rawPlan?.steps) ? rawPlan.steps : [];
  let invalidStepCount = 0;
  let invalidArgsCount = 0;
  for (const rawStep of rawSteps) {
    const step = asRecord(rawStep);
    if (!step) {
      invalidStepCount += 1;
      continue;
    }
    if (asRecord(step.args)) continue;
    if (typeof step.args !== "string") {
      invalidArgsCount += 1;
      continue;
    }
    let decoded: unknown = step.args;
    let valid = false;
    for (
      let attempt = 0;
      typeof decoded === "string" && attempt < 3;
      attempt += 1
    ) {
      try {
        decoded = JSON.parse(decoded.trim());
        if (asRecord(decoded)) {
          valid = true;
          break;
        }
      } catch {
        valid = extractFirstJsonObject(String(decoded)) !== null;
        break;
      }
    }
    if (!valid) invalidArgsCount += 1;
  }
  return {
    rawStepCount: rawSteps.length,
    invalidStepCount,
    invalidArgsCount,
  };
}
