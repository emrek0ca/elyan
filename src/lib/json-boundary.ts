import { z } from "zod";

const MAX_JSON_BYTES = 256 * 1024;
const MAX_JSON_DEPTH = 8;
const MAX_JSON_KEYS_PER_OBJECT = 128;
const MAX_JSON_ITEMS_PER_ARRAY = 256;
const MAX_JSON_STRING_LENGTH = 32_000;
const MAX_JSON_NODES = 20_000;
const UNSAFE_JSON_KEYS = new Set(["__proto__", "constructor", "prototype"]);

function inspectJsonValue(
  value: unknown,
  depth: number,
  state: { nodes: number },
): string | null {
  state.nodes += 1;
  if (state.nodes > MAX_JSON_NODES) {
    return "JSON value contains too many nodes";
  }
  if (depth > MAX_JSON_DEPTH) {
    return "JSON value is nested too deeply";
  }
  if (typeof value === "string") {
    return value.length <= MAX_JSON_STRING_LENGTH
      ? null
      : "JSON string is too long";
  }
  if (value == null || typeof value === "number" || typeof value === "boolean") {
    return null;
  }
  if (Array.isArray(value)) {
    if (value.length > MAX_JSON_ITEMS_PER_ARRAY) {
      return "JSON array contains too many items";
    }
    for (const item of value) {
      const issue = inspectJsonValue(item, depth + 1, state);
      if (issue) return issue;
    }
    return null;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length > MAX_JSON_KEYS_PER_OBJECT) {
      return "JSON object contains too many keys";
    }
    for (const [key, item] of entries) {
      if (UNSAFE_JSON_KEYS.has(key)) {
        return "JSON object contains an unsafe key";
      }
      if (key.length > 256) {
        return "JSON object key is too long";
      }
      const issue = inspectJsonValue(item, depth + 1, state);
      if (issue) return issue;
    }
  }
  return null;
}

export function validateBoundedJsonRecord(value: Record<string, unknown>): string | null {
  let serializedBytes = 0;
  try {
    serializedBytes = Buffer.byteLength(JSON.stringify(value), "utf8");
  } catch {
    return "JSON value could not be serialized";
  }
  if (serializedBytes > MAX_JSON_BYTES) {
    return "JSON value is too large";
  }
  return inspectJsonValue(value, 0, { nodes: 0 });
}

// Validate the original object before Zod's record parser can strip special
// keys such as `__proto__`, `constructor`, or `prototype`.
export const boundedJsonRecordSchema = z
  .unknown()
  .superRefine((value, ctx) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: "JSON value must be an object" });
      return;
    }
    const issue = validateBoundedJsonRecord(value as Record<string, unknown>);
    if (issue) {
      ctx.addIssue({ code: z.ZodIssueCode.custom, message: issue });
    }
  })
  .transform((value) => value as Record<string, unknown>);

export const BOUNDED_JSON_LIMITS = {
  maxBytes: MAX_JSON_BYTES,
  maxDepth: MAX_JSON_DEPTH,
  maxKeysPerObject: MAX_JSON_KEYS_PER_OBJECT,
  maxItemsPerArray: MAX_JSON_ITEMS_PER_ARRAY,
  maxStringLength: MAX_JSON_STRING_LENGTH,
  maxNodes: MAX_JSON_NODES,
} as const;
