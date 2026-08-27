import { createHash } from "node:crypto";
import type { FastifyInstance, FastifyRequest } from "fastify";
import { eq } from "drizzle-orm";
import { subscriptions } from "../../db/schema.js";
import { AppError } from "../errors.js";
import { nlpDaemon } from "../nlp-daemon.js";
import { asRecord as readRecord } from "../record.js";

export type RequestBudgetOptions = {
  scope: string;
  identity: string;
  max: number;
  windowMs: number;
};

function hashIdentity(identity: string): string {
  return createHash("sha256").update(identity).digest("hex").slice(0, 32);
}

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stableHash(value: string): string {
  return createHash("sha256").update(value.trim().toLowerCase()).digest("hex").slice(0, 24);
}

function readPath(request: FastifyRequest): string {
  return request.url.split("?")[0] ?? request.url;
}

function readPlanCodeFromRequest(request: FastifyRequest): string {
  const auth = request.auth as { planCode?: unknown } | undefined;
  const planCode = readString(auth?.planCode).toLowerCase();
  return planCode || "free";
}

async function resolvePlanCode(app: FastifyInstance, request: FastifyRequest): Promise<string> {
  const userId = request.auth?.sub;
  if (!userId) {
    return "free";
  }
  const authPlan = readPlanCodeFromRequest(request);
  if (authPlan !== "free") {
    return authPlan;
  }
  const cacheKey = `admission:plan:${userId}`;
  const cached = await app.services.reliability.store.get(cacheKey).catch(() => null);
  if (cached) {
    return cached;
  }
  const rows = await app.db
    .select({ planCode: subscriptions.planCode })
    .from(subscriptions)
    .where(eq(subscriptions.userId, userId))
    .limit(1)
    .catch(() => []);
  const planCode = String(rows[0]?.planCode ?? "free").trim().toLowerCase() || "free";
  await app.services.reliability.store.set(cacheKey, planCode, 60_000).catch(() => undefined);
  return planCode;
}

function readDeviceIdentity(request: FastifyRequest): string {
  const headers = request.headers;
  return firstNonEmpty(
    headers["x-elyan-device-id"],
    headers["x-device-id"],
    readRecord(request.body)?.deviceId,
    readRecord(readRecord(request.body)?.metadata)?.deviceId,
  );
}

function firstNonEmpty(...values: unknown[]): string {
  for (const value of values) {
    const text = readString(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function readBodyText(request: FastifyRequest): string {
  const body = readRecord(request.body);
  const metadata = readRecord(body?.metadata);
  return firstNonEmpty(
    body?.content,
    body?.prompt,
    body?.title,
    metadata?.prompt,
    metadata?.query,
  ).slice(0, 2000);
}

function readAuthCredentialIdentity(request: FastifyRequest): string {
  const body = readRecord(request.body);
  const provider = readPath(request).split("/").pop() ?? "auth";
  return firstNonEmpty(body?.email, body?.displayName, provider, "auth");
}

function routeAdmissionProfile(request: FastifyRequest): {
  scope: string;
  max: number;
  windowMs: number;
  text: string;
  costWeight: number;
} | null {
  const path = readPath(request);
  if (path.startsWith("/v1/auth/")) {
    return {
      scope: "auth",
      max: 8,
      windowMs: 60_000,
      text: readAuthCredentialIdentity(request),
      costWeight: 1,
    };
  }
  if (request.method === "POST" && path === "/v1/chat/messages") {
    return {
      scope: "chat",
      max: 40,
      windowMs: 60_000,
      text: readBodyText(request),
      costWeight: 2,
    };
  }
  if (request.method === "POST" && (path === "/v1/tasks" || path === "/v1/tasks/")) {
    return {
      scope: "tasks",
      max: 24,
      windowMs: 60_000,
      text: readBodyText(request),
      costWeight: 3,
    };
  }
  if (request.method === "POST" && path === "/v1/billing/store/verify") {
    return {
      scope: "billing_store_verify",
      max: 8,
      windowMs: 60_000,
      text: firstNonEmpty(readRecord(request.body)?.productId, "store_verify"),
      costWeight: 2,
    };
  }
  if (request.method === "GET" && path === "/v1/realtime/stream") {
    return {
      scope: "realtime_stream",
      max: 12,
      windowMs: 60_000,
      text: "realtime_stream",
      costWeight: 1,
    };
  }
  return null;
}

function maxForPlan(baseMax: number, planCode: string, degraded: boolean): number {
  const normalized = planCode.trim().toLowerCase();
  const multiplier = normalized === "pro" ? 2.5 : normalized === "solo" ? 1.5 : 1;
  const degradedMultiplier = degraded ? 0.5 : 1;
  return Math.max(2, Math.floor(baseMax * multiplier * degradedMultiplier));
}

function createRateLimitedError(retryAfterSeconds: number): AppError {
  return new AppError(429, "rate_limited", "Elyan şu anda çok hızlı istek alıyor. Birkaç saniye sonra tekrar dene.", {
    retryAfterSeconds,
    transient: true,
  });
}

async function recordAdmissionMetric(app: FastifyInstance, key: string, ttlMs = 86_400_000): Promise<void> {
  await app.services.reliability.store.increment(`metrics:admission:${key}`, ttlMs).catch(() => 0);
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
  const profile = routeAdmissionProfile(request);
  if (!profile) {
    return;
  }

  const planCode = await resolvePlanCode(app, request);
  const storeSummary = app.services.reliability.store.summary();
  const degraded = app.config.NODE_ENV === "production" && storeSummary.mode !== "redis";
  const ip = request.ip || "unknown";
  const userAgentHash = stableHash(String(request.headers["user-agent"] ?? "unknown"));
  const deviceHash = stableHash(readDeviceIdentity(request) || "no-device");
  const userIdentity = resolveBudgetIdentity(request);
  const primaryIdentity = request.auth?.sub
    ? `user:${request.auth.sub}:device:${deviceHash}`
    : `ip:${stableHash(ip)}:ua:${userAgentHash}`;
  const routeMax = maxForPlan(profile.max, planCode, degraded);
  const credentialIdentity = profile.scope === "auth" ? stableHash(readAuthCredentialIdentity(request)) : "";
  const textHash = profile.text ? stableHash(profile.text) : "no-text";
  const cSignals = nlpDaemon.isAvailable()
    ? await nlpDaemon.abuseScore({
        text: profile.text,
        scope: profile.scope,
        plan: planCode,
        hasAuth: Boolean(request.auth?.sub),
        hasDevice: deviceHash !== stableHash("no-device"),
        costWeight: profile.costWeight,
      }).catch(() => null)
    : null;
  const cRate = nlpDaemon.isAvailable()
    ? await nlpDaemon.rateCheckV2({
        identity: primaryIdentity,
        plan: planCode,
        scope: profile.scope,
        costWeight: profile.costWeight,
      }).catch(() => null)
    : null;
  const riskScore = Math.max(cRate && !cRate.allowed ? 0.7 : 0, cSignals?.score ?? fallbackAbuseScore(profile.text, {
    hasAuth: Boolean(request.auth?.sub),
    hasDevice: deviceHash !== stableHash("no-device"),
    costWeight: profile.costWeight,
  }));
  const riskTightening = riskScore >= 0.82 ? 0.25 : riskScore >= 0.65 ? 0.5 : 1;
  const effectiveMax = Math.max(1, Math.floor(routeMax * riskTightening));

  const current = await app.services.reliability.store.increment(
    `admission:${profile.scope}:${primaryIdentity}`,
    profile.windowMs,
  );
  if (current > effectiveMax) {
    await recordAdmissionMetric(app, "throttled");
    throw createRateLimitedError(Math.ceil(profile.windowMs / 1000));
  }

  if (credentialIdentity) {
    const credentialCount = await app.services.reliability.store.increment(
      `admission:${profile.scope}:credential:${credentialIdentity}:ip:${stableHash(ip)}`,
      profile.windowMs,
    );
    if (credentialCount > Math.max(3, Math.floor(effectiveMax / 2))) {
      await recordAdmissionMetric(app, "credential_throttled");
      throw createRateLimitedError(Math.ceil(profile.windowMs / 1000));
    }
  }

  if (profile.scope === "chat" || profile.scope === "tasks") {
    const duplicateCount = await app.services.reliability.store.increment(
      `admission:${profile.scope}:duplicate:${primaryIdentity}:${textHash}`,
      20_000,
    );
    if (duplicateCount > 3) {
      await recordAdmissionMetric(app, "duplicate_throttled");
      throw createRateLimitedError(20);
    }
  }

  if (riskScore >= 0.65) {
    await recordAdmissionMetric(app, "risk");
  }
}

function fallbackAbuseScore(
  text: string,
  input: { hasAuth: boolean; hasDevice: boolean; costWeight: number },
): number {
  const trimmed = text.trim();
  let score = 0;
  if (!input.hasAuth) score += 0.18;
  if (!input.hasDevice) score += 0.08;
  if (input.costWeight >= 3) score += 0.12;
  if (!trimmed) score += 0.2;
  if (trimmed.length > 1500) score += 0.12;
  if (/https?:\/\/|<script|select\s+.+from|drop\s+table/i.test(trimmed)) score += 0.2;
  if (/(.)\1{12,}/.test(trimmed)) score += 0.18;
  return Math.max(0, Math.min(1, score));
}
