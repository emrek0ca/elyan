const INTERNAL_ERROR_KEY_PATTERN = /(?:provider|model|engine|apikey|credential|secret|systemprompt|developer|reasoning|tooltrace|visionblock|fallbackstate|attemptedproviders|attemptedmodels|attemptfailures|providerstatus|failureclass|lasterror|rawresponse|debug)$/u;

function normalizeKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]/g, "");
}

export function sanitizePublicErrorDetails(value: unknown, depth = 0): unknown {
  if (value == null || typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "string") return value.trim().slice(0, 500);
  if (typeof value !== "object" || depth >= 6) return null;
  if (Array.isArray(value)) {
    return value.slice(0, 40).map((item) => sanitizePublicErrorDetails(item, depth + 1));
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !INTERNAL_ERROR_KEY_PATTERN.test(normalizeKey(key)))
      .slice(0, 40)
      .map(([key, nested]) => [key, sanitizePublicErrorDetails(nested, depth + 1)]),
  );
}
