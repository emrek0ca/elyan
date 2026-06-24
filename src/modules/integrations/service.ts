import { createHash } from "node:crypto";
import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  integrationConnections,
  integrationCredentials,
  oauthStates,
} from "../../db/schema.js";
import type { ConnectionProvider } from "../../contracts/domain.js";
import { decryptJson, encryptJson } from "../../lib/crypto-seal.js";
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

type GoogleOAuthPayload = {
  accessToken: string;
  refreshToken: string | null;
  tokenType: string;
  scope: string | null;
  raw: Record<string, unknown>;
};

function buildEmailMimeMessage(input: {
  from: string;
  to: string[];
  cc?: string[];
  bcc?: string[];
  replyTo?: string;
  subject: string;
  body: string;
}) {
  const lines = [
    `From: ${input.from}`,
    `To: ${input.to.join(", ")}`,
  ];
  if (input.cc?.length) {
    lines.push(`Cc: ${input.cc.join(", ")}`);
  }
  if (input.bcc?.length) {
    lines.push(`Bcc: ${input.bcc.join(", ")}`);
  }
  if (input.replyTo) {
    lines.push(`Reply-To: ${input.replyTo}`);
  }
  lines.push("MIME-Version: 1.0");
  lines.push('Content-Type: text/plain; charset="UTF-8"');
  lines.push("Content-Transfer-Encoding: 8bit");
  lines.push(`Subject: ${input.subject}`);
  lines.push("");
  lines.push(input.body);
  return lines.join("\r\n");
}

async function loadGoogleOAuthConnection(
  app: FastifyInstance,
  input: {
    userId: string;
    connectionId?: string;
  },
) {
  const connectionConditions = [eq(integrationConnections.userId, input.userId), eq(integrationConnections.provider, "google")];
  if (input.connectionId) {
    connectionConditions.push(eq(integrationConnections.id, input.connectionId));
  }

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
    .where(and(...connectionConditions))
    .orderBy(desc(integrationConnections.updatedAt));

  const connection = rows.find((row) => row.status === "connected" && Array.isArray(row.capabilities) && row.capabilities.includes("gmail"));
  if (!connection) {
    throw notFound("Connected Google Gmail integration not found");
  }
  return connection;
}

async function loadGoogleOAuthTokenPayload(app: FastifyInstance, connectionId: string) {
  const rows = await app.db
    .select({
      id: integrationCredentials.id,
      encryptedPayload: integrationCredentials.encryptedPayload,
      expiresAt: integrationCredentials.expiresAt,
    })
    .from(integrationCredentials)
    .where(eq(integrationCredentials.connectionId, connectionId))
    .limit(1);

  const credential = rows[0];
  if (!credential) {
    throw notFound("Integration credentials not found");
  }

  return {
    credential,
    tokenPayload: decryptJson<GoogleOAuthPayload>(app.config, credential.encryptedPayload),
  };
}

async function refreshGoogleOAuthAccessToken(
  app: FastifyInstance,
  connectionId: string,
  refreshToken: string,
) {
  const provider = getIntegrationProvider("google");
  if (!provider?.oauth) {
    throw badRequest("Google OAuth provider is not configured");
  }
  const clientId = app.config[provider.oauth.clientIdEnvKey];
  const clientSecret = app.config[provider.oauth.clientSecretEnvKey];
  if (!clientId || !clientSecret) {
    throw badRequest("Google OAuth provider is not configured");
  }

  const response = await fetch(provider.oauth.tokenUrl, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: refreshToken,
      client_id: clientId,
      client_secret: clientSecret,
    }).toString(),
  });
  const payload = (await parseJsonResponse(response)) as Record<string, unknown>;
  if (!response.ok || payload.error) {
    throw badRequest("Google access token refresh failed", payload);
  }

  const accessToken = typeof payload.access_token === "string" ? payload.access_token : "";
  if (!accessToken) {
    throw badRequest("Google provider did not return an access token");
  }

  const encryptedPayload = encryptJson(app.config, {
    accessToken,
    refreshToken: typeof payload.refresh_token === "string" ? payload.refresh_token : refreshToken,
    tokenType: typeof payload.token_type === "string" ? payload.token_type : "Bearer",
    scope: typeof payload.scope === "string" ? payload.scope : null,
    raw: payload,
  });

  await app.db
    .update(integrationCredentials)
    .set({
      encryptedPayload,
      expiresAt: getExpiresAtFromTokenPayload(payload),
      updatedAt: new Date(),
    })
    .where(eq(integrationCredentials.connectionId, connectionId));

  return {
    accessToken,
    refreshToken: typeof payload.refresh_token === "string" ? payload.refresh_token : refreshToken,
  };
}

async function getGoogleMailAccessToken(app: FastifyInstance, connectionId: string) {
  const { credential, tokenPayload } = await loadGoogleOAuthTokenPayload(app, connectionId);
  if (credential.expiresAt && credential.expiresAt.getTime() <= Date.now()) {
    if (!tokenPayload.refreshToken) {
      throw badRequest("Google Gmail connection needs re-authentication");
    }
    return refreshGoogleOAuthAccessToken(app, connectionId, tokenPayload.refreshToken);
  }
  if (!tokenPayload.accessToken) {
    if (!tokenPayload.refreshToken) {
      throw badRequest("Google Gmail connection needs re-authentication");
    }
    return refreshGoogleOAuthAccessToken(app, connectionId, tokenPayload.refreshToken);
  }
  return {
    accessToken: tokenPayload.accessToken,
    refreshToken: tokenPayload.refreshToken,
  };
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

  const requestPayload: Record<string, string> = {
    grant_type: "authorization_code",
    code,
    redirect_uri: getCallbackUrl(app, provider),
  };

  if (entry.oauth.usePkce && codeVerifier) {
    requestPayload.code_verifier = codeVerifier;
  }

  const tokenRequestStyle = entry.oauth.tokenRequestStyle ?? "form";
  const requestInit: RequestInit = {
    method: "POST",
    headers: {
      Accept: "application/json",
    },
  };

  if (tokenRequestStyle === "json_basic") {
    requestInit.headers = {
      ...requestInit.headers,
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`,
      "Content-Type": "application/json",
    };
    requestInit.body = JSON.stringify(requestPayload);
  } else if (tokenRequestStyle === "json") {
    requestInit.headers = {
      ...requestInit.headers,
      "Content-Type": "application/json",
    };
    requestInit.body = JSON.stringify({
      ...requestPayload,
      client_id: clientId,
      client_secret: clientSecret,
    });
  } else {
    const form = new URLSearchParams({
      ...requestPayload,
      client_id: clientId,
      client_secret: clientSecret,
    });

    requestInit.headers = {
      ...requestInit.headers,
      "Content-Type": "application/x-www-form-urlencoded",
    };
    requestInit.body = form.toString();
  }

  const response = await fetch(entry.oauth.tokenUrl, {
    ...requestInit,
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

export async function sendGmailMessage(
  app: FastifyInstance,
  input: {
    userId: string;
    connectionId?: string;
    to: string[];
    subject: string;
    body: string;
    cc?: string[];
    bcc?: string[];
    replyTo?: string;
    ipAddress?: string;
    userAgent?: string;
    requestId?: string;
  },
) {
  const connection = await loadGoogleOAuthConnection(app, {
    userId: input.userId,
    connectionId: input.connectionId,
  });
  const scopes = Array.isArray(connection.scopes) ? connection.scopes.map((value) => String(value ?? "").trim()) : [];
  if (!scopes.includes("https://www.googleapis.com/auth/gmail.send")) {
    throw badRequest("Google Gmail send scope is missing");
  }

  const token = await getGoogleMailAccessToken(app, connection.id);
  const mimeMessage = buildEmailMimeMessage({
    from: connection.displayName || "Elyan",
    to: input.to,
    cc: input.cc,
    bcc: input.bcc,
    replyTo: input.replyTo,
    subject: input.subject,
    body: input.body,
  });

  const response = await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token.accessToken}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      raw: Buffer.from(mimeMessage, "utf8").toString("base64url"),
    }),
  });
  const payload = (await parseJsonResponse(response)) as Record<string, unknown>;
  if (!response.ok || payload.error) {
    throw badRequest("Gmail message send failed", payload);
  }

  const messageId = typeof payload.id === "string" ? payload.id : "";
  const threadId = typeof payload.threadId === "string" ? payload.threadId : "";
  const labelIds = Array.isArray(payload.labelIds)
    ? payload.labelIds.map((value) => String(value ?? "").trim()).filter(Boolean)
    : [];

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "integration.gmail.send",
    resourceType: "integration_connection",
    resourceId: connection.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    requestId: input.requestId,
    payload: {
      provider: "google",
      to: input.to,
      subject: input.subject,
    },
  });

  return {
    provider: "google",
    connectionId: connection.id,
    messageId,
    threadId,
    labelIds,
    to: input.to,
    subject: input.subject,
  };
}
