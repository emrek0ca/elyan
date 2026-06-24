import { createHash } from "node:crypto";
import type { FastifyRequest } from "fastify";
import { badRequest } from "./errors.js";

const IDEMPOTENCY_KEY_MIN_LENGTH = 8;
const IDEMPOTENCY_KEY_MAX_LENGTH = 160;

function normalizeValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((entry) => normalizeValue(entry));
  }

  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .reduce<Record<string, unknown>>((accumulator, [key, entry]) => {
        accumulator[key] = normalizeValue(entry);
        return accumulator;
      }, {});
  }

  return value;
}

export function createIdempotencyFingerprint(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(normalizeValue(value))).digest("hex");
}

export function getIdempotencyKey(request: FastifyRequest): string | undefined {
  const header = request.headers["idempotency-key"];
  const value =
    typeof header === "string" ? header.trim() : Array.isArray(header) ? String(header[0] || "").trim() : "";

  if (!value) {
    return undefined;
  }

  if (value.length < IDEMPOTENCY_KEY_MIN_LENGTH || value.length > IDEMPOTENCY_KEY_MAX_LENGTH) {
    throw badRequest(
      `Idempotency-Key must be between ${IDEMPOTENCY_KEY_MIN_LENGTH} and ${IDEMPOTENCY_KEY_MAX_LENGTH} characters`,
    );
  }

  return value;
}
