import type { FastifyInstance, FastifyPluginAsync, FastifyReply, FastifyRequest } from "fastify";
import { badRequest } from "../../lib/errors.js";
import { getRequestContext, sendConditionalJson } from "../../lib/http.js";
import { assertRequestBudget } from "../../lib/reliability/request-budget.js";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  changePasswordBodySchema,
  loginBodySchema,
  oauthLoginBodySchema,
  oauthProviderParamsSchema,
  refreshBodySchema,
  registerBodySchema,
  updateProfileBodySchema,
  uploadAvatarBodySchema,
} from "./schemas.js";
import {
  changeCurrentUserPassword,
  deleteCurrentUserAvatar,
  deleteCurrentUserAccount,
  getCurrentUserAvatar,
  getCurrentUserProfile,
  loginUser,
  loginWithApple,
  loginWithGoogle,
  refreshUserSession,
  registerUser,
  revokeUserSession,
  updateCurrentUserProfile,
  upsertCurrentUserAvatar,
} from "./service.js";

function firstNonEmpty(...values: Array<unknown>): string {
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (text) {
      return text;
    }
  }
  return "";
}

function normalizeBudgetIdentity(value: unknown): string {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .slice(0, 160);
}

async function enforceAuthCredentialBudget(
  app: FastifyInstance,
  request: FastifyRequest,
  scope: string,
  identity: string,
) {
  const ip = normalizeBudgetIdentity(request.ip || "unknown");
  const normalizedIdentity = normalizeBudgetIdentity(identity);

  await assertRequestBudget(app, {
    scope,
    identity: normalizedIdentity ? `${ip}:${normalizedIdentity}` : ip,
    max: 5,
    windowMs: app.config.REQUEST_BUDGET_WINDOW_MS,
  });
}

export function normalizeAppleCallbackPayload(body: unknown, query: unknown) {
  const bodyRecord = body && typeof body === "object" && !Array.isArray(body) ? (body as Record<string, unknown>) : {};
  const queryRecord = query && typeof query === "object" && !Array.isArray(query) ? (query as Record<string, unknown>) : {};
  const source = {
    ...queryRecord,
    ...bodyRecord,
  };

  return {
    authorizationCode: firstNonEmpty(source.authorizationCode, source.authorization_code, source.code),
    displayName: firstNonEmpty(source.displayName, source.display_name),
    email: firstNonEmpty(source.email),
    idToken: firstNonEmpty(source.idToken, source.id_token, source.identityToken, source.identity_token),
    state: firstNonEmpty(source.state),
    user: firstNonEmpty(source.user),
  };
}

export function buildAppleCallbackLandingHtml() {
  return [
    "<!doctype html>",
    '<html lang="tr">',
    "<head>",
    '  <meta charset="utf-8" />',
    '  <meta name="viewport" content="width=device-width, initial-scale=1" />',
    "  <title>Elyan</title>",
    '  <meta http-equiv="cache-control" content="no-store" />',
    '  <meta name="robots" content="noindex,nofollow" />',
    "</head>",
    "<body>",
    "  <p>Giriş tamamlandı. Bu pencereyi kapatabilirsiniz.</p>",
    "</body>",
    "</html>",
  ].join("\n");
}

export async function handleAppleCallbackRequest(request: FastifyRequest, reply: FastifyReply) {
  normalizeAppleCallbackPayload(request.body, request.query);

  reply
    .header("cache-control", "no-store, max-age=0, must-revalidate")
    .header("pragma", "no-cache")
    .header("x-robots-tag", "noindex, nofollow")
    .header("content-security-policy", "default-src 'none'; frame-ancestors 'none'; form-action 'none'")
    .type("text/html; charset=utf-8");

  return reply.code(200).send(buildAppleCallbackLandingHtml());
}

export const authRoutes: FastifyPluginAsync = async (app) => {
  app.post("/register", async (request, reply) => {
    const body = registerBodySchema.parse(request.body);
    await enforceAuthCredentialBudget(app, request, "auth_register_credential", body.email);
    reply.header("cache-control", "no-store, max-age=0, must-revalidate");
    reply.header("pragma", "no-cache");
    return registerUser(app, body, getRequestContext(request));
  });

  app.post("/login", async (request, reply) => {
    const body = loginBodySchema.parse(request.body);
    await enforceAuthCredentialBudget(app, request, "auth_login_credential", body.email);
    reply.header("cache-control", "no-store, max-age=0, must-revalidate");
    reply.header("pragma", "no-cache");
    return loginUser(app, body, getRequestContext(request));
  });

  app.post("/refresh", async (request, reply) => {
    const body = refreshBodySchema.parse(request.body);
    await enforceAuthCredentialBudget(app, request, "auth_refresh_ip", "refresh");
    reply.header("cache-control", "no-store, max-age=0, must-revalidate");
    reply.header("pragma", "no-cache");
    return refreshUserSession(app, body.refreshToken, getRequestContext(request));
  });

  app.post("/oauth/:provider", async (request, reply) => {
    const params = oauthProviderParamsSchema.parse(request.params);
    const parsedBody = oauthLoginBodySchema.safeParse(request.body);

    if (!parsedBody.success) {
      throw badRequest("Invalid request payload", parsedBody.error.issues);
    }

    const body = parsedBody.data;
    await enforceAuthCredentialBudget(
      app,
      request,
      `auth_oauth_${params.provider}`,
      `${params.provider}:${body.email ?? body.displayName ?? "oauth"}`,
    );
    reply.header("cache-control", "no-store, max-age=0, must-revalidate");
    reply.header("pragma", "no-cache");
    if (params.provider === "google") {
      return loginWithGoogle(app, body, getRequestContext(request));
    }
    return loginWithApple(app, body, getRequestContext(request));
  });

  app.get("/callback/apple", handleAppleCallbackRequest);
  app.post("/callback/apple", handleAppleCallbackRequest);

  app.post("/logout", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    await revokeUserSession(app, auth.sessionId);

    return {
      ok: true,
    };
  });

  app.get("/me", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const payload = await getCurrentUserProfile(app, auth.sub);
    return sendConditionalJson(request, reply, payload);
  });

  app.patch("/me", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = updateProfileBodySchema.parse(request.body);
    const context = getRequestContext(request);
    return updateCurrentUserProfile(app, {
      userId: auth.sub,
      displayName: body.displayName,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });

  app.post("/password", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = changePasswordBodySchema.parse(request.body);
    const context = getRequestContext(request);
    return changeCurrentUserPassword(app, {
      userId: auth.sub,
      currentPassword: body.currentPassword,
      nextPassword: body.nextPassword,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });

  app.post("/avatar", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = uploadAvatarBodySchema.parse(request.body);
    const context = getRequestContext(request);
    return upsertCurrentUserAvatar(app, {
      userId: auth.sub,
      mimeType: body.mimeType,
      dataBase64: body.dataBase64,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });

  app.get("/avatar", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const avatar = await getCurrentUserAvatar(app, auth.sub);
    reply.header("cache-control", "private, max-age=60");
    reply.type(avatar.mimeType);
    return Buffer.from(avatar.dataBase64, "base64");
  });

  app.delete("/avatar", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    return deleteCurrentUserAvatar(app, {
      userId: auth.sub,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });

  app.delete("/me", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const context = getRequestContext(request);
    return deleteCurrentUserAccount(app, {
      userId: auth.sub,
      sessionId: auth.sessionId,
      ipAddress: context.ipAddress,
      userAgent: context.userAgent,
      requestId: context.requestId,
    });
  });
};
