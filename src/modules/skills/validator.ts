import AjvModule, { type ValidateFunction } from "ajv/dist/2020.js";
import type { SkillDefinition } from "./types.js";

const Ajv = AjvModule.default ?? AjvModule;
const ajv = new Ajv({
  allErrors: true,
  strict: false,
});

let definitionValidator: ValidateFunction | null = null;
const outputValidators = new Map<string, ValidateFunction>();
const inputValidators = new Map<string, ValidateFunction>();

function formatErrors(validate: ValidateFunction): string {
  return (validate.errors ?? [])
    .map((error) => `${error.instancePath || "/"} ${error.message ?? "is invalid"}`)
    .join("; ");
}

export function configureSkillDefinitionSchema(schema: Record<string, unknown>) {
  definitionValidator = ajv.compile(schema);
}

export function validateSkillDefinition(value: unknown): SkillDefinition {
  if (!definitionValidator) {
    throw new Error("skill_definition_schema_not_configured");
  }

  if (!definitionValidator(value)) {
    throw new Error(`invalid_skill_definition:${formatErrors(definitionValidator)}`);
  }

  return value as SkillDefinition;
}

export function validateSkillInput(skill: SkillDefinition, value: unknown): {
  ok: boolean;
  error?: string;
} {
  const key = `${skill.id}:${skill.version}:input`;
  let validate = inputValidators.get(key);
  if (!validate) {
    validate = ajv.compile(skill.inputSchema);
    inputValidators.set(key, validate);
  }
  const ok = validate(value);
  return ok ? { ok: true } : { ok: false, error: formatErrors(validate) };
}

export function validateSkillOutput(skill: SkillDefinition, value: unknown): {
  ok: boolean;
  error?: string;
} {
  const key = `${skill.id}:${skill.version}:output`;
  let validate = outputValidators.get(key);
  if (!validate) {
    validate = ajv.compile(skill.outputSchema);
    outputValidators.set(key, validate);
  }
  const ok = validate(value);
  return ok ? { ok: true } : { ok: false, error: formatErrors(validate) };
}

export function parseStrictJsonObject(value: string): Record<string, unknown> | null {
  const trimmed = value.trim();
  const candidate =
    trimmed.startsWith("{") && trimmed.endsWith("}")
      ? trimmed
      : trimmed.match(/\{[\s\S]*\}/)?.[0] ?? "";

  if (!candidate) {
    return null;
  }

  try {
    const parsed = JSON.parse(candidate);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}
