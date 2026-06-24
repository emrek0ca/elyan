import { createHash } from "node:crypto";
import type { FastifyInstance, FastifyRequest } from "fastify";
import { AppError } from "../errors.js";

export type RequestBudgetOptions = {
  scope: string;
  identity: string;
  max: number;
  windowMs: number;
};

function hashIdentity(identity: string): string {
  return createHash("sha256").update(identity).digest("hex").slice(0, 32);
}

export async function assertRequestBudget(app: FastifyInstance, options: RequestBudgetOptions): Promise<void> {
  const key = `budget:${options.scope}:${hashIdentity(options.identity)}`;
  const current = await app.services.reliability.store.increment(key, options.windowMs);

  if (current <= options.max) {
    return;
  }

  throw new AppError(429, "request_budget_exceeded", "Çok fazla istek gönderildi. Lütfen kısa süre sonra tekrar dene.", {
    scope: options.scope,
    retryAfterSeconds: Math.ceil(options.windowMs / 1000),
  });
}

export function resolveBudgetIdentity(request: FastifyRequest): string {
  return request.auth?.sub ?? request.ip ?? "anonymous";
}

export async function enforceRouteRequestBudget(app: FastifyInstance, request: FastifyRequest): Promise<void> {
  const url = request.url.split("?")[0] ?? request.url;
  const identity = resolveBudgetIdentity(request);

  if (url.startsWith("/v1/auth/")) {
    await assertRequestBudget(app, {
      scope: "auth",
      identity,
      max: app.config.AUTH_REQUEST_BUDGET_MAX,
      windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
    });
    return;
  }

  if (request.method === "POST" && url === "/v1/chat/messages") {
    await assertRequestBudget(app, {
      scope: "chat",
      identity,
      max: app.config.CHAT_REQUEST_BUDGET_MAX,
      windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
    });
    return;
  }

  if (request.method === "POST" && (url === "/v1/tasks" || url === "/v1/tasks/")) {
    await assertRequestBudget(app, {
      scope: "tasks",
      identity,
      max: app.config.TASK_REQUEST_BUDGET_MAX,
      windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
    });
  }
}
