import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { z } from "zod";
import { AppError } from "../lib/errors.js";
import { errorHandlerPlugin } from "./error-handler.js";

test("error handler converts route Zod failures into safe validation responses", async () => {
  const app = Fastify({ logger: false });
  await app.register(errorHandlerPlugin);
  app.post("/login", async (request) => {
    return z.object({ email: z.string().email() }).parse(request.body);
  });

  const response = await app.inject({
    method: "POST",
    url: "/login",
    payload: {
      email: "x' OR 1=1 --",
    },
  });

  assert.equal(response.statusCode, 400);
  assert.equal(response.json().error, "validation_error");
  assert.equal(response.json().message, "Invalid request payload");
  assert.doesNotMatch(response.body, /stack|select|syntax error/i);
  await app.close();
});

test("error handler preserves rate limit failures as 429 responses", async () => {
  const app = Fastify({ logger: false });
  await app.register(errorHandlerPlugin);
  app.get("/limited", async () => {
    const error = new Error("Rate limit exceeded, retry in 12 seconds") as Error & {
      statusCode: number;
    };
    error.statusCode = 429;
    throw error;
  });

  const response = await app.inject({
    method: "GET",
    url: "/limited",
  });

  assert.equal(response.statusCode, 429);
  assert.equal(response.headers["retry-after"], "12");
  assert.equal(response.json().error, "rate_limited");
  assert.equal(response.json().details.retryAfterMs, 12_000);
  assert.doesNotMatch(response.body, /stack/i);
  await app.close();
});

test("error handler keeps Fastify empty JSON parser errors as client errors", async () => {
  const app = Fastify({ logger: false });
  await app.register(errorHandlerPlugin);
  app.delete("/me", async () => ({ ok: true }));

  const response = await app.inject({
    method: "DELETE",
    url: "/me",
    headers: {
      "content-type": "application/json",
    },
    payload: "",
  });

  assert.equal(response.statusCode, 400);
  assert.equal(response.json().error, "invalid_request");
  assert.equal(response.json().message, "Invalid request payload");
  assert.doesNotMatch(response.body, /stack|Body cannot be empty/i);
  await app.close();
});

test("error handler preserves retry-after metadata for app rate limit errors", async () => {
  const app = Fastify({ logger: false });
  await app.register(errorHandlerPlugin);
  app.get("/budget", async () => {
    throw new AppError(
      429,
      "request_budget_exceeded",
      "Çok fazla istek gönderildi. Lütfen kısa süre sonra tekrar dene.",
      {
        scope: "auth_login_credential",
        retryAfterSeconds: 30,
      },
    );
  });

  const response = await app.inject({
    method: "GET",
    url: "/budget",
  });

  assert.equal(response.statusCode, 429);
  assert.equal(response.headers["retry-after"], "30");
  assert.equal(response.json().error, "request_budget_exceeded");
  assert.equal(response.json().details.retryAfterMs, 30_000);
  await app.close();
});

test("error handler removes provider and model metadata from public details", async () => {
  const app = Fastify({ logger: false });
  await app.register(errorHandlerPlugin);
  app.get("/brain", async () => {
    throw new AppError(503, "server_brain_unavailable", "Elyan şu anda yanıt veremiyor.", {
      retrySuggested: true,
      transient: true,
      provider: "gemini",
      model: "private-vision-model",
      attemptedProviders: ["gemini", "groq"],
      nested: {
        fallbackState: "provider_failed",
        retryAfterMs: 2_000,
      },
    });
  });
  const response = await app.inject({ method: "GET", url: "/brain" });
  assert.equal(response.statusCode, 503);
  assert.deepEqual(response.json().details, {
    retrySuggested: true,
    transient: true,
    nested: { retryAfterMs: 2_000 },
  });
  assert.doesNotMatch(response.body, /gemini|groq|private-vision-model|fallbackState/iu);
  await app.close();
});
