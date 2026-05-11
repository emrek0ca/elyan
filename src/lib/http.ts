import type { FastifyRequest } from "fastify";
import { ZodError } from "zod";

export function getRequestContext(request: FastifyRequest): { ipAddress?: string; userAgent?: string } {
  return {
    ipAddress: request.ip,
    userAgent: request.headers["user-agent"],
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
