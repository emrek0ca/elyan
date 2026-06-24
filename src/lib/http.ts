import { createHash, timingSafeEqual } from "node:crypto";
import type { FastifyReply, FastifyRequest } from "fastify";
import { ZodError } from "zod";

export function getRequestContext(
  request: FastifyRequest,
): { ipAddress?: string; userAgent?: string; requestId: string } {
  return {
    ipAddress: request.ip,
    userAgent: request.headers["user-agent"],
    requestId: request.id,
  };
}

export function serializeZodError(error: ZodError): Array<{ path: string; message: string }> {
  return error.issues.map((issue) => ({
    path: issue.path.join("."),
    message: issue.message,
  }));
}

export function getHeaderString(value: string | string[] | undefined): string | undefined {
  if (typeof value === "string") {
    return value;
  }

  if (Array.isArray(value)) {
    return value[0];
  }

  return undefined;
}

export function buildWeakEtag(payload: unknown): string {
  const serialized = typeof payload === "string" ? payload : JSON.stringify(payload);
  const hash = createHash("sha256").update(serialized).digest("hex");
  return `W/"${hash}"`;
}

export function requestAcceptsEtag(request: FastifyRequest, etag: string): boolean {
  const header = getHeaderString(request.headers["if-none-match"]);
  const normalized = header?.trim() ?? "";
  if (!normalized) {
    return false;
  }
  const candidates = normalized.split(",").map((value) => value.trim()).filter(Boolean);
  for (const candidate of candidates) {
    if (candidate === "*") {
      return true;
    }
    const left = Buffer.from(candidate);
    const right = Buffer.from(etag);
    if (left.length === right.length && timingSafeEqual(left, right)) {
      return true;
    }
  }
  return false;
}

export function sendConditionalJson(
  request: FastifyRequest,
  reply: FastifyReply,
  payload: unknown,
  options: {
    cacheControl?: string;
    statusCode?: number;
  } = {},
) {
  const etag = buildWeakEtag(payload);
  reply.header("etag", etag);
  reply.header(
    "cache-control",
    options.cacheControl ?? "private, max-age=0, must-revalidate",
  );
  if (requestAcceptsEtag(request, etag)) {
    return reply.code(304).send();
  }
  if (options.statusCode != null) {
    reply.code(options.statusCode);
  }
  return reply.send(payload);
}
