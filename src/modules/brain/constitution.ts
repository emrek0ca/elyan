import constitutionRules from "./constitution.rules.json" with { type: "json" };
import { z } from "zod";

const elyanConstitutionRuleSchema = z.object({
  id: z.string().min(1),
  version: z.string().min(1),
  category: z.string().min(1),
  severity: z.enum(["critical", "high", "medium", "low"]),
  appliesTo: z.array(z.string().min(1)).min(1),
  expectedBehavior: z.string().min(1),
  failureType: z.string().min(1),
  gateEnforced: z.boolean(),
});

const elyanConstitutionDocumentSchema = z.object({
  version: z.string().min(1),
  promptProfileVersion: z.string().min(1),
  rules: z.array(elyanConstitutionRuleSchema).min(1),
});

export type ElyanConstitutionRule = z.infer<typeof elyanConstitutionRuleSchema>;
type ElyanConstitutionDocument = z.infer<typeof elyanConstitutionDocumentSchema>;

const document = elyanConstitutionDocumentSchema.parse(constitutionRules) as ElyanConstitutionDocument;

export const ELYAN_CONSTITUTION_VERSION = document.version;
export const ELYAN_PROMPT_PROFILE_VERSION = document.promptProfileVersion;
export const ELYAN_CONSTITUTION_RULES = document.rules;
export const ELYAN_CONSTITUTION_GATE_READY = ELYAN_CONSTITUTION_RULES.some((rule) => rule.gateEnforced);

export function getElyanConstitution() {
  return {
    version: ELYAN_CONSTITUTION_VERSION,
    promptProfileVersion: ELYAN_PROMPT_PROFILE_VERSION,
    rules: ELYAN_CONSTITUTION_RULES,
  };
}

export function getElyanConstitutionRule(ruleId: string): ElyanConstitutionRule | null {
  return ELYAN_CONSTITUTION_RULES.find((rule) => rule.id === ruleId) ?? null;
}

export function listGateEnforcedRuleIds(): string[] {
  return ELYAN_CONSTITUTION_RULES.filter((rule) => rule.gateEnforced).map((rule) => rule.id);
}

export function constitutionRuleCount(): number {
  return ELYAN_CONSTITUTION_RULES.length;
}
