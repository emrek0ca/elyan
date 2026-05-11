import { createHash } from "node:crypto";
import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  integrationConnections,
  integrationCredentials,
  oauthStates,
} from "../../db/schema.js";
import type { ConnectionProvider } from "../../contracts/domain.js";
import { encryptJson } from "../../lib/crypto-seal.js";
import { badRequest, notFound } from "../../lib/errors.js";
import { createOpaqueCode } from "../../lib/auth-crypto.js";
import { createPkcePair } from "../../lib/oauth-pkce.js";
import { createAuditLog } from "../audit/service.js";
import { getIntegrationProvider, integrationProviderCatalog, isProviderConfigured } from "./provider-registry.js";

function getCallbackUrl(app: FastifyInstance, provider: ConnectionProvider): string {
  return `${app.config.APP_BASE_URL}/v1/integrations/oauth/${provider}/callback`;
}

function joinScopes(scopes: string[], separator = " "): string {
  return scopes.join(separator);
}

function redirectWithStatus(baseUrl: string, params: Record<string, string>): string {
  const url = new URL(baseUrl);

  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }

  return url.toString();
}

function getExpiresAtFromTokenPayload(tokenPayload: Record<string, unknown>): Date | undefined {
  const expiresIn = tokenPayload.expires_in;
  if (typeof expiresIn !== "number" || !Number.isFinite(expiresIn)) {
    return undefined;
  }

  return new Date(Date.now() + expiresIn * 1_000);
}

async function parseJsonResponse(response: Response) {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    return response.json();
  }

  const text = await response.text();

  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return Object.fromEntries(new URLSearchParams(text));
  }
}

async function exchangeOAuthCode(
  app: FastifyInstance,
  provider: ConnectionProvider,
  code: string,
  codeVerifier: string | null,
) {
  const entry = getIntegrationProvider(provider);

  if (!entry?.oauth) {
    throw badRequest(`Provider ${provider} does not support OAuth2`);
  }

  const clientId = app.config[entry.oauth.clientIdEnvKey];
  const clientSecret = app.config[entry.oauth.clientSecretEnvKey];

  if (!clientId || !clientSecret) {
    throw badRequest(`Provider ${provider} is not configured`);
  }

  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    client_id: clientId,
    client_secret: clientSecret,
    redirect_uri: getCallbackUrl(app, provider),
  });

  if (entry.oauth.usePkce && codeVerifier) {
    form.set("code_verifier", codeVerifier);
  }

  const response = await fetch(entry.oauth.tokenUrl, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: form.toString(),
  });
  const payload = (await parseJsonResponse(response)) as Record<string, unknown>;

  if (!response.ok || payload.error) {
    throw badRequest(`OAuth token exchange failed for ${provider}`, payload);
  }

  return payload;
}

async function fetchProviderIdentity(provider: ConnectionProvider, accessToken: string) {
  switch (provider) {
    case "google": {
      const response = await fetch("https://www.googleapis.com/oauth2/v3/userinfo", {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const payload = (await parseJsonResponse(response)) as Record<string, unknown>;
      return {
        externalAccountId: String(payload.sub ?? payload.email ?? ""),
        displayName: String(payload.name ?? payload.email ?? "Google"),
        metadata: payload,
      };
    }
    case "github": {
      const response = await fetch("https://api.github.com/user", {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: "application/vnd.github+json",
        },
      });
      const payload = (await parseJsonResponse(response)) as Record<string, unknown>;
      return {
        externalAccountId: String(payload.id ?? payload.login ?? ""),
        displayName: String(payload.login ?? payload.name ?? "GitHub"),
        metadata: payload,
      };
    }
    case "discord": {
      const response = await fetch("https://discord.com/api/users/@me", {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const payload = (await parseJsonResponse(response)) as Record<string, unknown>;
      return {
        externalAccountId: String(payload.id ?? ""),
        displayName: String(payload.username ?? "Discord"),
        metadata: payload,
      };
    }
    case "dropbox": {
      const response = await fetch("https://api.dropboxapi.com/2/users/get_current_account", {
        method: "POST",
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      const payload = (await parseJsonResponse(response)) as Record<string, unknown>;
      return {
        externalAccountId: String(payload.account_id ?? ""),
        displayName: String(payload.name && typeof payload.name === "object" ? (payload.name as { display_name?: string }).display_name ?? "Dropbox" : "Dropbox"),
        metadata: payload,
      };
    }
    default:
      return {
        externalAccountId: undefined,
        displayName: provider,
        metadata: {},
      };
  }
}

export async function listIntegrationProviders(app: FastifyInstance) {
  return integrationProviderCatalog.map((provider) => ({
    code: provider.code,
    displayName: provider.displayName,
    authType: provider.authType,
    capabilities: provider.capabilities,
    configured: isProviderConfigured(app.config, provider.code),
    oauthSupported: Boolean(provider.oauth),
  }));
}

export async function listUserIntegrationConnections(
  app: FastifyInstance,
  userId: string,
  provider?: ConnectionProvider,
) {
  const rows = await app.db
    .select({
      id: integrationConnections.id,
      provider: integrationConnections.provider,
      authType: integrationConnections.authType,
      status: integrationConnections.status,
      displayName: integrationConnections.displayName,
      externalAccountId: integrationConnections.externalAccountId,
      scopes: integrationConnections.scopes,
      capabilities: integrationConnections.capabilities,
      metadata: integrationConnections.metadata,
      updatedAt: integrationConnections.updatedAt,
    })
    .from(integrationConnections)
    .where(
      provider
        ? and(eq(integrationConnections.userId, userId), eq(integrationConnections.provider, provider))
        : eq(integrationConnections.userId, userId),
    )
    .orderBy(desc(integrationConnections.updatedAt));

  return rows;
}

export async function startOauthConnection(
  app: FastifyInstance,
  input: {
    userId: string;
    provider: ConnectionProvider;
    redirectUri?: string;
    scopes?: string[];
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const entry = getIntegrationProvider(input.provider);

  if (!entry?.oauth) {
    throw badRequest(`Provider ${input.provider} does not support OAuth2`);
  }

  if (!isProviderConfigured(app.config, input.provider)) {
    throw badRequest(`Provider ${input.provider} is not configured`);
  }

  const state = createOpaqueCode(24);
  const scopes = input.scopes?.length ? input.scopes : entry.oauth.defaultScopes;
  const pkce = entry.oauth.usePkce ? createPkcePair() : null;
  const expiresAt = new Date(Date.now() + app.config.OAUTH_STATE_TTL_MINUTES * 60_000);

  await app.db.insert(oauthStates).values({
    userId: input.userId,
    provider: input.provider,
    state,
    redirectUri: input.redirectUri,
    requestedScopes: scopes,
    codeVerifier: pkce?.verifier,
    expiresAt,
  });

  const authUrl = new URL(entry.oauth.authUrl);
  authUrl.searchParams.set("client_id", String(app.config[entry.oauth.clientIdEnvKey]));
  authUrl.searchParams.set("redirect_uri", getCallbackUrl(app, input.provider));
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("state", state);

  if (scopes.length > 0) {
    authUrl.searchParams.set("scope", joinScopes(scopes, entry.oauth.scopeSeparator));
  }

  if (pkce) {
    authUrl.searchParams.set("code_challenge_method", "S256");
    authUrl.searchParams.set("code_challenge", pkce.challenge);
  }

  for (const [key, value] of Object.entries(entry.oauth.extraAuthParams ?? {})) {
    authUrl.searchParams.set(key, value);
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "integration.oauth.start",
    resourceType: "oauth_state",
    resourceId: state,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      provider: input.provider,
      scopeHash: createHash("sha256").update(JSON.stringify(scopes)).digest("hex"),
    },
  });

  return {
    provider: input.provider,
    authUrl: authUrl.toString(),
    state,
    expiresAt,
  };
}

export async function handleOauthCallback(
  app: FastifyInstance,
  input: {
    provider: ConnectionProvider;
    state: string;
    code?: string;
    error?: string;
    errorDescription?: string;
  },
) {
    const stateRows = await app.db
      .select()
      .from(oauthStates)
      .where(and(eq(oauthStates.state, input.state), eq(oauthStates.provider, input.provider)))
      .limit(1);

    const oauthState = stateRows[0];

    if (!oauthState) {
      throw notFound("OAuth state not found");
    }

    if (oauthState.expiresAt.getTime() <= Date.now()) {
      await app.db
        .update(oauthStates)
        .set({
          status: "expired",
        })
        .where(eq(oauthStates.id, oauthState.id));
      throw badRequest("OAuth state has expired");
    }

    if (input.error) {
      await app.db
        .update(oauthStates)
        .set({
          status: "expired",
          consumedAt: new Date(),
        })
        .where(eq(oauthStates.id, oauthState.id));

      return {
        redirectUri: oauthState.redirectUri,
        status: "error" as const,
        provider: input.provider,
        error: input.errorDescription ?? input.error,
      };
    }

    if (!input.code) {
      throw badRequest("OAuth callback code is missing");
    }

    const tokenPayload = await exchangeOAuthCode(app, input.provider, input.code, oauthState.codeVerifier);
    const accessToken = tokenPayload.access_token;

    if (typeof accessToken !== "string" || !accessToken) {
      throw badRequest("OAuth provider did not return an access token");
    }

    const identity = await fetchProviderIdentity(input.provider, accessToken);
    const existingConnectionRows = await app.db
      .select({
        id: integrationConnections.id,
      })
      .from(integrationConnections)
      .where(and(eq(integrationConnections.userId, oauthState.userId), eq(integrationConnections.provider, input.provider)))
      .limit(1);

    const connectionRows =
      existingConnectionRows[0]
        ? await app.db
            .update(integrationConnections)
            .set({
              authType: getIntegrationProvider(input.provider)?.authType ?? "oauth2",
              status: "connected",
              displayName: identity.displayName,
              externalAccountId: identity.externalAccountId,
              scopes: Array.isArray(oauthState.requestedScopes) ? oauthState.requestedScopes : [],
              capabilities: getIntegrationProvider(input.provider)?.capabilities ?? [],
              metadata: identity.metadata ?? {},
              lastSyncedAt: new Date(),
              updatedAt: new Date(),
            })
            .where(eq(integrationConnections.id, existingConnectionRows[0].id))
            .returning()
        : await app.db
            .insert(integrationConnections)
            .values({
              userId: oauthState.userId,
              provider: input.provider,
              authType: getIntegrationProvider(input.provider)?.authType ?? "oauth2",
              status: "connected",
              displayName: identity.displayName,
              externalAccountId: identity.externalAccountId,
              scopes: Array.isArray(oauthState.requestedScopes) ? oauthState.requestedScopes : [],
              capabilities: getIntegrationProvider(input.provider)?.capabilities ?? [],
              metadata: identity.metadata ?? {},
              lastSyncedAt: new Date(),
            })
            .returning();

    const connection = connectionRows[0];
    const encryptedPayload = encryptJson(app.config, {
      accessToken,
      refreshToken: typeof tokenPayload.refresh_token === "string" ? tokenPayload.refresh_token : null,
      tokenType: typeof tokenPayload.token_type === "string" ? tokenPayload.token_type : "Bearer",
      scope: typeof tokenPayload.scope === "string" ? tokenPayload.scope : null,
      raw: tokenPayload,
    });

    const existingCredentialRows = await app.db
      .select({
        id: integrationCredentials.id,
      })
      .from(integrationCredentials)
      .where(eq(integrationCredentials.connectionId, connection.id))
      .limit(1);

    if (existingCredentialRows[0]) {
      await app.db
        .update(integrationCredentials)
        .set({
          encryptedPayload,
          expiresAt: getExpiresAtFromTokenPayload(tokenPayload),
          updatedAt: new Date(),
        })
        .where(eq(integrationCredentials.id, existingCredentialRows[0].id));
    } else {
      await app.db.insert(integrationCredentials).values({
        connectionId: connection.id,
        encryptedPayload,
        expiresAt: getExpiresAtFromTokenPayload(tokenPayload),
      });
    }

    await app.db
      .update(oauthStates)
      .set({
        status: "completed",
        consumedAt: new Date(),
      })
      .where(eq(oauthStates.id, oauthState.id));

    await createAuditLog(app, {
      userId: oauthState.userId,
      actorType: "user",
      actorId: oauthState.userId,
      action: "integration.oauth.callback",
      resourceType: "integration_connection",
      resourceId: connection.id,
      status: "success",
      payload: {
        provider: input.provider,
      },
    });

    return {
      redirectUri: oauthState.redirectUri,
      status: "connected" as const,
      provider: input.provider,
      connectionId: connection.id,
    };
}

export async function disconnectIntegration(
  app: FastifyInstance,
  input: {
    userId: string;
    connectionId: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const rows = await app.db
    .update(integrationConnections)
    .set({
      status: "revoked",
      updatedAt: new Date(),
    })
    .where(and(eq(integrationConnections.id, input.connectionId), eq(integrationConnections.userId, input.userId)))
    .returning();

  const connection = rows[0];

  if (!connection) {
    throw notFound("Integration connection not found");
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "integration.disconnect",
    resourceType: "integration_connection",
    resourceId: connection.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      provider: connection.provider,
    },
  });

  return connection;
}
