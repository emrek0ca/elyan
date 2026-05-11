import fp from "fastify-plugin";
import { ZodError } from "zod";
import { AppError } from "../lib/errors.js";
import { serializeZodError } from "../lib/http.js";

export const errorHandlerPlugin = fp(async (app) => {
  app.setErrorHandler((error, _request, reply) => {
    if (error instanceof ZodError) {
      reply.status(400).send({
        error: "validation_error",
        message: "Invalid request payload",
        details: serializeZodError(error),
      });
      return;
    }

    if (error instanceof AppError) {
      reply.status(error.statusCode).send({
        error: error.code,
        message: error.message,
        details: error.details,
      });
      return;
    }

    if (typeof error === "object" && error && "code" in error && error.code === "23505") {
      reply.status(409).send({
        error: "conflict",
        message: "Resource already exists",
      });
      return;
    }

    app.log.error({ err: error }, "request failed");

    reply.status(500).send({
      error: "internal_error",
      message: "Internal server error",
    });
  });
});
