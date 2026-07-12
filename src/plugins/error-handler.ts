import fp from "fastify-plugin";
import { ZodError } from "zod";
import { AppError } from "../lib/errors.js";
import { serializeZodError } from "../lib/http.js";
import { sanitizePublicErrorDetails } from "../lib/public-error-details.js";

function readRetryAfterSeconds(details: unknown): number | null {
  if (!details || typeof details !== "object" || Array.isArray(details)) {
    return null;
  }

  const value = (details as Record<string, unknown>).retryAfterSeconds;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

export const errorHandlerPlugin = fp(async (app) => {
  app.setErrorHandler((error, request, reply) => {
    reply.header("x-request-id", request.id);

    if (error instanceof ZodError) {
      reply.status(400).send({
        error: "validation_error",
        message: "Invalid request payload",
        details: serializeZodError(error),
        requestId: request.id,
      });
      return;
    }

    if (error instanceof AppError) {
      const retryAfterSeconds =
        error.statusCode === 429 || error.statusCode === 503
          ? readRetryAfterSeconds(error.details)
          : null;
      if (retryAfterSeconds != null) {
        reply.header("retry-after", String(retryAfterSeconds));
      }
      if (error.statusCode === 409) {
        app.log.warn({ err: { code: error.code, message: error.message, details: error.details }, requestId: request.id, url: request.url }, "409 app error");
      }
      const publicDetails = sanitizePublicErrorDetails(error.details);
      reply.status(error.statusCode).send({
        error: error.code,
        message: error.message,
        details:
          retryAfterSeconds == null
            ? publicDetails
            : {
                ...(typeof publicDetails === "object" && publicDetails && !Array.isArray(publicDetails)
                  ? publicDetails
                  : {}),
                retryAfterMs: retryAfterSeconds * 1000,
              },
        requestId: request.id,
      });
      return;
    }

    if (typeof error === "object" && error && "code" in error && error.code === "23505") {
      app.log.warn({ err: error, requestId: request.id, url: request.url }, "409 unique constraint violation");
      reply.status(409).send({
        error: "conflict",
        message: "Resource already exists",
        requestId: request.id,
      });
      return;
    }

    if (isHttpClientError(error)) {
      const statusCode = Number((error as { statusCode: number }).statusCode);
      app.log.warn({ err: error, requestId: request.id, url: request.url }, "client request error");
      reply.status(statusCode).send({
        error: "invalid_request",
        message: "Invalid request payload",
        requestId: request.id,
      });
      return;
    }

    if (
      typeof error === "object" &&
      error &&
      "statusCode" in error &&
      error.statusCode === 429
    ) {
      const retryAfterSeconds = parseRetryAfterSeconds(
        "message" in error ? String(error.message) : "",
      );
      if (retryAfterSeconds != null) {
        reply.header("retry-after", String(retryAfterSeconds));
      }
      reply.status(429).send({
        error: "rate_limited",
        message: "Rate limit exceeded",
        details:
          retryAfterSeconds == null
            ? undefined
            : { retryAfterMs: retryAfterSeconds * 1000 },
        requestId: request.id,
      });
      return;
    }

    app.log.error({ err: error, requestId: request.id }, "request failed");

    reply.status(500).send({
      error: "internal_error",
      message: "Internal server error",
      requestId: request.id,
    });
  });
});

function isHttpClientError(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("statusCode" in error)) {
    return false;
  }
  const statusCode = Number((error as { statusCode?: unknown }).statusCode);
  return Number.isInteger(statusCode) && statusCode >= 400 && statusCode < 500 && statusCode !== 429;
}

function parseRetryAfterSeconds(message: string): number | null {
  const match = /retry in\s+(\d+)\s+seconds?/i.exec(message);
  if (!match) {
    return null;
  }
  const value = Number.parseInt(match[1] ?? "", 10);
  return Number.isFinite(value) && value > 0 ? value : null;
}
