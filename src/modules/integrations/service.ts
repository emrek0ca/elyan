import { createHash } from "node:crypto";
import { isIP } from "node:net";
import { and, desc, eq, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import {
  integrationConnections,
  integrationCredentials,
  mcpServers,
  oauthStates,
} from "../../db/schema.js";
import type { ConnectionProvider } from "../../contracts/domain.js";
import { decryptJson, encryptJson } from "../../lib/crypto-seal.js";
import { AppError, badRequest, notFound } from "../../lib/errors.js";
import { createOpaqueCode } from "../../lib/auth-crypto.js";
import { createPkcePair } from "../../lib/oauth-pkce.js";
import { createAuditLog } from "../audit/service.js";
import {
  isConnectionMcpProbeFresh,
  readConnectionMcpProbe,
} from "./mcp-probe.js";
import { rankSemanticTextCandidates } from "../../core/understanding/intent-semantic.js";
import {
  classifyConnectedDataOperationSemantic,
  getIntegrationMcpApp,
  getIntegrationProvider,
  inferRequestedRemoteMcpSelectionSemantic,
  integrationMcpAppCatalog,
  integrationProviderCatalog,
  isIntegrationMcpAppConfigured,
  isProviderConfigured,
  type RemoteMcpSelectionMetadata,
} from "./provider-registry.js";

function getCallbackUrl(
  app: FastifyInstance,
  provider: ConnectionProvider,
): string {
  return `${app.config.APP_BASE_URL}/v1/integrations/oauth/${provider}/callback`;
}

function getOauthClientCredentials(
  app: FastifyInstance,
  provider: ConnectionProvider,
  appId?: string,
) {
  const providerEntry = getIntegrationProvider(provider);
  if (!providerEntry?.oauth) {
    throw badRequest(`Provider ${provider} does not support OAuth2`);
  }
  const oauth = providerEntry.oauth;
  const catalogEntry = appId ? getIntegrationMcpApp(appId) : undefined;
  const clientIdKey =
    catalogEntry?.oauthClientIdEnvKey ?? providerEntry.oauth.clientIdEnvKey;
  const clientSecretKey =
    catalogEntry?.oauthClientSecretEnvKey ??
    providerEntry.oauth.clientSecretEnvKey;
  const clientId = app.config[clientIdKey];
  const clientSecret = app.config[clientSecretKey];
  if (
    typeof clientId !== "string" ||
    typeof clientSecret !== "string" ||
    !clientId ||
    !clientSecret
  ) {
    throw badRequest(`Provider ${provider} is not configured`);
  }
  return {
    providerEntry: { ...providerEntry, oauth },
    clientId,
    clientSecret,
  };
}

function joinScopes(scopes: string[], separator = " "): string {
  return scopes.join(separator);
}

function redirectWithStatus(
  baseUrl: string,
  params: Record<string, string>,
): string {
  const url = new URL(baseUrl);

  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }

  return url.toString();
}

function getExpiresAtFromTokenPayload(
  tokenPayload: Record<string, unknown>,
): Date | undefined {
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

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item ?? "").trim())
    .filter((item) => item.length > 0);
}

const GOOGLE_OAUTH_SCOPE_ALIASES = new Map<string, string>([
  ["email", "email"],
  ["https://www.googleapis.com/auth/userinfo.email", "email"],
  ["profile", "profile"],
  ["https://www.googleapis.com/auth/userinfo.profile", "profile"],
  // The broad `calendar.readonly` scope (what the top-level Google login
  // requests and Google grants) genuinely covers the granular calendar READ
  // scopes the calendar tool requires. Without these aliases a user who
  // connected via the broad login held `calendar.readonly` but the granular
  // required scopes never matched, so the calendar tool was never advertised
  // and calendar queries fell through to web grounding ("no reliable data").
  // Write access (`calendar.events`) is intentionally NOT aliased — real writes
  // still need the write scope.
  ["https://www.googleapis.com/auth/calendar.readonly", "google.calendar.read"],
  ["https://www.googleapis.com/auth/calendar.events.readonly", "google.calendar.read"],
  ["https://www.googleapis.com/auth/calendar.calendarlist.readonly", "google.calendar.read"],
  ["https://www.googleapis.com/auth/calendar.events.freebusy", "google.calendar.read"],
]);

function canonicalOauthScope(
  provider: ConnectionProvider | string,
  scope: string,
): string {
  return provider === "google"
    ? (GOOGLE_OAUTH_SCOPE_ALIASES.get(scope) ?? scope)
    : scope;
}

export function missingOauthScopes(
  provider: ConnectionProvider | string,
  grantedScopes: string[],
  requiredScopes: string[],
): string[] {
  const granted = new Set(
    grantedScopes.map((scope) => canonicalOauthScope(provider, scope)),
  );
  return requiredScopes.filter(
    (scope) => !granted.has(canonicalOauthScope(provider, scope)),
  );
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function mergeUnique(...lists: string[][]): string[] {
  return [
    ...new Set(
      lists
        .flat()
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  ];
}

function grantedOauthScopes(
  tokenPayload: Record<string, unknown>,
  requestedScopes: unknown,
): string[] {
  const granted = String(tokenPayload.scope ?? "")
    .split(/[\s,]+/)
    .map((scope) => scope.trim())
    .filter(Boolean);
  return granted.length > 0
    ? mergeUnique(granted)
    : stringList(requestedScopes);
}

export function normalizeOauthRedirectUri(
  redirectUri: string | undefined,
  appBaseUrl: string,
): string | undefined {
  const raw = redirectUri?.trim();
  if (!raw) return undefined;

  let target: URL;
  let appBase: URL;
  try {
    target = new URL(raw);
    appBase = new URL(appBaseUrl);
  } catch {
    throw badRequest("OAuth redirect URI is invalid");
  }

  if (
    target.protocol === "elyan:" &&
    ["connections", "oauth-complete"].includes(target.hostname) &&
    (target.pathname === "" || target.pathname === "/") &&
    !target.username &&
    !target.password &&
    !target.port &&
    !target.hash
  ) {
    const flowValues = target.searchParams.getAll("flow");
    if (
      flowValues.length > 1 ||
      (flowValues[0] && !/^[a-f0-9]{32}$/i.test(flowValues[0]))
    ) {
      throw badRequest("OAuth redirect URI correlation token is invalid");
    }
    const safeTarget = new URL(`${target.protocol}//${target.hostname}`);
    if (flowValues[0]) {
      safeTarget.searchParams.set("flow", flowValues[0]);
    }
    return safeTarget.toString();
  }

  if (target.protocol === "https:" && target.origin === appBase.origin) {
    return target.toString();
  }

  throw badRequest("OAuth redirect URI is not allowed");
}

function buildEmailMimeMessage(input: {
  from: string;
  to: string[];
  cc?: string[];
  bcc?: string[];
  replyTo?: string;
  subject: string;
  body: string;
}) {
  const lines = [`From: ${input.from}`, `To: ${input.to.join(", ")}`];
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
  const connectionConditions = [
    eq(integrationConnections.userId, input.userId),
    eq(integrationConnections.provider, "google"),
  ];
  if (input.connectionId) {
    connectionConditions.push(
      eq(integrationConnections.id, input.connectionId),
    );
  }

  const rows = await app.db
    .select({
      id: integrationConnections.id,
      appId: integrationConnections.appId,
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

  const connection = rows.find(
    (row) =>
      row.status === "connected" &&
      Array.isArray(row.capabilities) &&
      row.capabilities.includes("gmail"),
  );
  if (!connection) {
    throw notFound("Connected Google Gmail integration not found");
  }
  return connection;
}

async function loadGoogleOAuthTokenPayload(
  app: FastifyInstance,
  connectionId: string,
) {
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
    tokenPayload: decryptJson<GoogleOAuthPayload>(
      app.config,
      credential.encryptedPayload,
    ),
  };
}

/**
 * Ölü refresh token'lı bağlantıyı görünür şekilde işaretler: status →
 * "error" (enum'daki mevcut değer; neden ayrımı audit kaydında).
 * listConnectedCapabilityGrants yalnız "connected" filtreler, dolayısıyla
 * yetenek reklamı otomatik düşer; mobil liste uçları da yalnız "connected"ı
 * bağlı sayar → uygulama dürüstçe "Bağlan" gösterir. Yalnız "connected" satır
 * güncellenir (revoked/error ezilmez); işaretleme hatası asıl
 * connector_auth_required hatasını asla gölgelemez.
 */
export async function markConnectionAuthExpired(
  app: FastifyInstance,
  connectionId: string,
  provider: string,
): Promise<void> {
  try {
    const rows = await app.db
      .update(integrationConnections)
      .set({ status: "error", updatedAt: new Date() })
      .where(
        and(
          eq(integrationConnections.id, connectionId),
          eq(integrationConnections.status, "connected"),
        ),
      )
      .returning({ userId: integrationConnections.userId });
    const userId = rows[0]?.userId;
    if (!userId) return;
    await createAuditLog(app, {
      userId,
      actorType: "system",
      actorId: "connector-auth",
      action: "integration.auth.expired",
      resourceType: "integration_connection",
      resourceId: connectionId,
      status: "success",
      payload: { provider, reason: "invalid_grant" },
    });
  } catch {
    // İşaretleme başarısız olsa da akış connector_auth_required ile sürer.
  }
}

async function refreshGoogleOAuthAccessToken(
  app: FastifyInstance,
  connectionId: string,
  refreshToken: string,
  appId?: string,
  timeoutMs = 12_000,
) {
  const {
    providerEntry: provider,
    clientId,
    clientSecret,
  } = getOauthClientCredentials(app, "google", appId);

  const response = await fetch(provider.oauth.tokenUrl, {
    signal: AbortSignal.timeout(timeoutMs),
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
  const payload = (await parseJsonResponse(response)) as Record<
    string,
    unknown
  >;
  if (!response.ok || payload.error) {
    // invalid_grant = refresh token ölü — kullanıcı bağlantıyı yenilemeli.
    if (payload.error === "invalid_grant") {
      await markConnectionAuthExpired(app, connectionId, "google");
      throw new AppError(
        400,
        "connector_auth_required",
        "Google refresh token is no longer valid; the user must reconnect the integration",
      );
    }
    throw badRequest("Google access token refresh failed", payload);
  }

  const accessToken =
    typeof payload.access_token === "string" ? payload.access_token : "";
  if (!accessToken) {
    throw badRequest("Google provider did not return an access token");
  }

  const encryptedPayload = encryptJson(app.config, {
    accessToken,
    refreshToken:
      typeof payload.refresh_token === "string"
        ? payload.refresh_token
        : refreshToken,
    tokenType:
      typeof payload.token_type === "string" ? payload.token_type : "Bearer",
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
    refreshToken:
      typeof payload.refresh_token === "string"
        ? payload.refresh_token
        : refreshToken,
  };
}

async function refreshProviderOAuthAccessToken(
  app: FastifyInstance,
  connectionId: string,
  provider: ConnectionProvider,
  refreshToken: string,
  appId?: string,
  timeoutMs = 12_000,
): Promise<string> {
  const {
    providerEntry: entry,
    clientId,
    clientSecret,
  } = getOauthClientCredentials(app, provider, appId);
  const requestPayload = {
    grant_type: "refresh_token",
    refresh_token: refreshToken,
  };
  const requestInit: RequestInit = {
    method: "POST",
    headers: { Accept: "application/json" },
  };

  if (entry.oauth.tokenRequestStyle === "json_basic") {
    requestInit.headers = {
      ...requestInit.headers,
      Authorization: `Basic ${Buffer.from(`${clientId}:${clientSecret}`).toString("base64")}`,
      "Content-Type": "application/json",
    };
    requestInit.body = JSON.stringify(requestPayload);
  } else if (entry.oauth.tokenRequestStyle === "json") {
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
    requestInit.headers = {
      ...requestInit.headers,
      "Content-Type": "application/x-www-form-urlencoded",
    };
    requestInit.body = new URLSearchParams({
      ...requestPayload,
      client_id: clientId,
      client_secret: clientSecret,
    }).toString();
  }

  let response: Response;
  try {
    response = await fetch(entry.oauth.tokenUrl, {
      ...requestInit,
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    throw badRequest(`OAuth access token refresh failed for ${provider}`);
  }
  const payload = (await parseJsonResponse(response)) as Record<
    string,
    unknown
  >;
  if (!response.ok || payload.error) {
    // invalid_grant = refresh token ölü (süre doldu / kullanıcı iptal etti).
    // Tek çözüm kullanıcının bağlantıyı yeniden kurması — connector katmanı
    // bu kodla "bağlantıyı yenile" yönlendirmesi gösterir; jenerik "sonra
    // tekrar dene" mesajı kullanıcıyı çıkmaza sokuyordu.
    if (payload.error === "invalid_grant") {
      await markConnectionAuthExpired(app, connectionId, provider);
      throw new AppError(
        400,
        "connector_auth_required",
        `OAuth refresh token is no longer valid for ${provider}; the user must reconnect the integration`,
      );
    }
    throw badRequest(`OAuth access token refresh failed for ${provider}`);
  }
  const accessToken =
    typeof payload.access_token === "string" ? payload.access_token : "";
  if (!accessToken) {
    throw badRequest(
      `OAuth provider ${provider} did not return an access token`,
    );
  }

  await app.db
    .update(integrationCredentials)
    .set({
      encryptedPayload: encryptJson(app.config, {
        accessToken,
        refreshToken:
          typeof payload.refresh_token === "string"
            ? payload.refresh_token
            : refreshToken,
        tokenType:
          typeof payload.token_type === "string"
            ? payload.token_type
            : "Bearer",
        scope: typeof payload.scope === "string" ? payload.scope : null,
        raw: payload,
      }),
      expiresAt: getExpiresAtFromTokenPayload(payload),
      updatedAt: new Date(),
    })
    .where(eq(integrationCredentials.connectionId, connectionId));

  return accessToken;
}

const PROVIDER_REVOKE_URLS: Partial<Record<ConnectionProvider, string>> = {
  google: "https://oauth2.googleapis.com/revoke",
  linear: "https://api.linear.app/oauth/revoke",
};

/**
 * Best-effort remote authorization revocation. Providers with a known revoke
 * endpoint must confirm success (fail-closed) so a live grant is not silently
 * kept upstream. Providers without one return `false` — the caller still
 * deletes the local encrypted credential, which is the security-meaningful
 * action, instead of blocking disconnect forever.
 */
async function revokeProviderAuthorization(
  app: FastifyInstance,
  connectionId: string,
  provider: ConnectionProvider,
): Promise<boolean> {
  const revokeUrl = PROVIDER_REVOKE_URLS[provider];
  if (!revokeUrl) {
    return false;
  }

  const { tokenPayload } = await loadGoogleOAuthTokenPayload(app, connectionId);
  const token = tokenPayload.refreshToken || tokenPayload.accessToken;
  if (!token) {
    // Nothing to revoke upstream; local deletion still fully disconnects.
    return false;
  }

  let response: Response;
  try {
    response = await fetch(revokeUrl, {
      method: "POST",
      signal: AbortSignal.timeout(10_000),
      headers: {
        Accept: "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({ token }).toString(),
    });
  } catch {
    throw badRequest("Provider authorization could not be revoked");
  }
  if (!response.ok) {
    throw badRequest("Provider authorization could not be revoked");
  }
  return true;
}

async function getGoogleMailAccessToken(
  app: FastifyInstance,
  connectionId: string,
  appId?: string,
  refreshTimeoutMs = 12_000,
) {
  const { credential, tokenPayload } = await loadGoogleOAuthTokenPayload(
    app,
    connectionId,
  );
  if (credential.expiresAt && credential.expiresAt.getTime() <= Date.now()) {
    if (!tokenPayload.refreshToken) {
      throw new AppError(400, "connector_auth_required", "Google Gmail connection needs re-authentication");
    }
    return refreshGoogleOAuthAccessToken(
      app,
      connectionId,
      tokenPayload.refreshToken,
      appId,
      refreshTimeoutMs,
    );
  }
  if (!tokenPayload.accessToken) {
    if (!tokenPayload.refreshToken) {
      throw new AppError(400, "connector_auth_required", "Google Gmail connection needs re-authentication");
    }
    return refreshGoogleOAuthAccessToken(
      app,
      connectionId,
      tokenPayload.refreshToken,
      appId,
      refreshTimeoutMs,
    );
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
  appId?: string,
) {
  const {
    providerEntry: entry,
    clientId,
    clientSecret,
  } = getOauthClientCredentials(app, provider, appId);

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
    signal: AbortSignal.timeout(12_000),
  });
  const payload = (await parseJsonResponse(response)) as Record<
    string,
    unknown
  >;

  if (!response.ok || payload.error) {
    throw badRequest(`OAuth token exchange failed for ${provider}`, payload);
  }

  return payload;
}

async function fetchProviderIdentity(
  provider: ConnectionProvider,
  accessToken: string,
) {
  switch (provider) {
    case "google": {
      const response = await fetch(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        {
          headers: { Authorization: `Bearer ${accessToken}` },
          signal: AbortSignal.timeout(10_000),
        },
      );
      const payload = (await parseJsonResponse(response)) as Record<
        string,
        unknown
      >;
      return {
        externalAccountId: String(payload.sub ?? payload.email ?? ""),
        displayName: String(payload.name ?? payload.email ?? "Google"),
        metadata: payload,
      };
    }
    case "github": {
      const response = await fetch("https://api.github.com/user", {
        signal: AbortSignal.timeout(10_000),
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: "application/vnd.github+json",
        },
      });
      const payload = (await parseJsonResponse(response)) as Record<
        string,
        unknown
      >;
      return {
        externalAccountId: String(payload.id ?? payload.login ?? ""),
        displayName: String(payload.login ?? payload.name ?? "GitHub"),
        metadata: payload,
      };
    }
    case "discord": {
      const response = await fetch("https://discord.com/api/users/@me", {
        headers: { Authorization: `Bearer ${accessToken}` },
        signal: AbortSignal.timeout(10_000),
      });
      const payload = (await parseJsonResponse(response)) as Record<
        string,
        unknown
      >;
      return {
        externalAccountId: String(payload.id ?? ""),
        displayName: String(payload.username ?? "Discord"),
        metadata: payload,
      };
    }
    case "dropbox": {
      const response = await fetch(
        "https://api.dropboxapi.com/2/users/get_current_account",
        {
          method: "POST",
          signal: AbortSignal.timeout(10_000),
          headers: { Authorization: `Bearer ${accessToken}` },
        },
      );
      const payload = (await parseJsonResponse(response)) as Record<
        string,
        unknown
      >;
      return {
        externalAccountId: String(payload.account_id ?? ""),
        displayName: String(
          payload.name && typeof payload.name === "object"
            ? ((payload.name as { display_name?: string }).display_name ??
                "Dropbox")
            : "Dropbox",
        ),
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

export async function listIntegrationApps(
  app: FastifyInstance,
  userId?: string,
) {
  const connections = userId
    ? await listUserIntegrationConnections(app, userId)
    : [];

  return integrationMcpAppCatalog.map((entry) => {
    const exactConnection = connections.find(
      (item) => item.status === "connected" && item.appId === entry.id,
    );
    const legacyProviderConnection =
      entry.execution === "server_connector"
        ? connections.find((item) => {
            if (
              item.status !== "connected" ||
              item.provider !== entry.provider ||
              item.appId
            ) {
              return false;
            }
            const capabilities = stringList(item.capabilities);
            return entry.capabilities.every((capability) =>
              capabilities.includes(capability),
            );
          })
        : undefined;
    const connection = exactConnection ?? legacyProviderConnection;
    const missingScopes = missingOauthScopes(
      entry.provider,
      stringList(connection?.scopes),
      entry.connectionScopes ?? entry.oauthScopes,
    );
    const configured = isIntegrationMcpAppConfigured(app.config, entry);
    const connected = Boolean(connection && missingScopes.length === 0);
    // Uzak MCP app'lerde bağlantı sonrası el sıkışma probu sonucu: mobil UI
    // "bağlı ama sunucu cevap vermiyor" durumunu dürüstçe gösterebilsin.
    const probe =
      connected && entry.execution === "remote_mcp"
        ? readConnectionMcpProbe(connection?.metadata, entry.id)
        : null;

    return {
      id: entry.id,
      provider: entry.provider,
      displayName: entry.displayName,
      description: entry.description,
      iconKey: entry.iconKey,
      category: entry.category,
      serverUrl: entry.serverUrl,
      transport: "streamable_http" as const,
      authType: "oauth2" as const,
      authStrategy: entry.authStrategy,
      stage: entry.stage,
      capabilities: entry.capabilities,
      configured,
      available: configured && entry.stage !== "setup_required",
      connected,
      connectionId: connected ? (connection?.id ?? null) : null,
      accountLabel: connected ? (connection?.displayName ?? null) : null,
      missingScopes,
      probeStatus:
        probe?.status ??
        (entry.execution === "remote_mcp" && connected ? "unknown" : null),
      probedAt: probe?.probedAt ?? null,
      probeErrorCode: probe?.errorCode ?? null,
      probeToolCount: probe?.toolCount ?? null,
    };
  });
}

export async function listUserIntegrationConnections(
  app: FastifyInstance,
  userId: string,
  provider?: ConnectionProvider,
) {
  const rows = await app.db
    .select({
      id: integrationConnections.id,
      appId: integrationConnections.appId,
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
        ? and(
            eq(integrationConnections.userId, userId),
            eq(integrationConnections.provider, provider),
          )
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
    appId?: string;
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

  const catalogEntry = input.appId
    ? getIntegrationMcpApp(input.appId)
    : undefined;
  if (
    input.appId &&
    (!catalogEntry || catalogEntry.provider !== input.provider)
  ) {
    throw badRequest("Integration app configuration is invalid");
  }
  if (
    catalogEntry
      ? !isIntegrationMcpAppConfigured(app.config, catalogEntry)
      : !isProviderConfigured(app.config, input.provider)
  ) {
    throw badRequest(`Provider ${input.provider} is not configured`);
  }
  const { clientId } = getOauthClientCredentials(
    app,
    input.provider,
    input.appId,
  );

  const state = createOpaqueCode(24);
  const redirectUri = normalizeOauthRedirectUri(
    input.redirectUri,
    app.config.APP_BASE_URL,
  );
  const existingRows = input.appId
    ? []
    : await app.db
        .select({ scopes: integrationConnections.scopes })
        .from(integrationConnections)
        .where(
          and(
            eq(integrationConnections.userId, input.userId),
            eq(integrationConnections.provider, input.provider),
          ),
        )
        .limit(1);
  const requestedScopes = input.scopes?.length
    ? input.scopes
    : entry.oauth.defaultScopes;
  const scopes = mergeUnique(
    stringList(existingRows[0]?.scopes),
    requestedScopes,
  );
  const pkce = entry.oauth.usePkce ? createPkcePair() : null;
  const expiresAt = new Date(Date.now() + 10 * 60_000);

  await app.db.insert(oauthStates).values({
    userId: input.userId,
    provider: input.provider,
    state,
    redirectUri,
    requestedScopes: scopes,
    codeVerifier: pkce?.verifier,
    metadata: input.appId ? { appId: input.appId } : {},
    expiresAt,
  });

  const authUrl = new URL(entry.oauth.authUrl);
  authUrl.searchParams.set("client_id", clientId);
  authUrl.searchParams.set("redirect_uri", getCallbackUrl(app, input.provider));
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("state", state);

  if (scopes.length > 0) {
    authUrl.searchParams.set(
      "scope",
      joinScopes(scopes, entry.oauth.scopeSeparator),
    );
  }

  if (pkce) {
    authUrl.searchParams.set("code_challenge_method", "S256");
    authUrl.searchParams.set("code_challenge", pkce.challenge);
  }

  for (const [key, value] of Object.entries(
    entry.oauth.extraAuthParams ?? {},
  )) {
    authUrl.searchParams.set(key, value);
  }

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "integration.oauth.start",
    resourceType: "oauth_state",
    resourceId: createHash("sha256").update(state).digest("hex"),
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      provider: input.provider,
      scopeHash: createHash("sha256")
        .update(JSON.stringify(scopes))
        .digest("hex"),
    },
  });

  return {
    provider: input.provider,
    authUrl: authUrl.toString(),
    state,
    expiresAt,
  };
}

export async function startOauthAppConnection(
  app: FastifyInstance,
  input: {
    userId: string;
    appId: string;
    redirectUri?: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const entry = getIntegrationMcpApp(input.appId);
  if (!entry) {
    throw notFound("Integration app not found");
  }
  if (entry.stage === "setup_required") {
    throw badRequest("Integration app requires provider setup");
  }
  return startOauthConnection(app, {
    userId: input.userId,
    provider: entry.provider,
    appId: entry.id,
    redirectUri: input.redirectUri,
    scopes: entry.oauthScopes,
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
  });
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
    .where(
      and(
        eq(oauthStates.state, input.state),
        eq(oauthStates.provider, input.provider),
      ),
    )
    .limit(1);

  const oauthState = stateRows[0];

  if (!oauthState) {
    throw notFound("OAuth state not found");
  }

  const oauthMetadata = recordValue(oauthState.metadata);
  const appId =
    typeof oauthMetadata.appId === "string" ? oauthMetadata.appId.trim() : "";

  if (oauthState.status !== "pending") {
    throw badRequest("OAuth state has already been used");
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

  const claimedRows = await app.db
    .update(oauthStates)
    .set({ status: "expired", consumedAt: new Date() })
    .where(
      and(eq(oauthStates.id, oauthState.id), eq(oauthStates.status, "pending")),
    )
    .returning({ id: oauthStates.id });
  if (!claimedRows[0]) {
    throw badRequest("OAuth state has already been used");
  }

  if (input.error) {
    return {
      redirectUri: oauthState.redirectUri,
      status: "error" as const,
      provider: input.provider,
      appId: appId || undefined,
      error: input.errorDescription ?? input.error,
    };
  }

  if (!input.code) {
    throw badRequest("OAuth callback code is missing");
  }

  const tokenPayload = await exchangeOAuthCode(
    app,
    input.provider,
    input.code,
    oauthState.codeVerifier,
    appId || undefined,
  );
  const accessToken = tokenPayload.access_token;

  if (typeof accessToken !== "string" || !accessToken) {
    throw badRequest("OAuth provider did not return an access token");
  }

  const identity = await fetchProviderIdentity(input.provider, accessToken);
  const effectiveScopes = grantedOauthScopes(
    tokenPayload,
    oauthState.requestedScopes,
  );
  const connection = await app.db.transaction(async (tx) => {
    const lockKey = `${oauthState.userId}:${appId || input.provider}`;
    await tx.execute(
      sql`select pg_advisory_xact_lock(hashtextextended(${lockKey}, 0))`,
    );

    const existingConnectionRows = await tx
      .select({
        id: integrationConnections.id,
        metadata: integrationConnections.metadata,
      })
      .from(integrationConnections)
      .where(
        appId
          ? and(
              eq(integrationConnections.userId, oauthState.userId),
              eq(integrationConnections.appId, appId),
            )
          : and(
              eq(integrationConnections.userId, oauthState.userId),
              eq(integrationConnections.provider, input.provider),
            ),
      )
      .limit(1);

    const previousMetadata = recordValue(existingConnectionRows[0]?.metadata);
    const enabledMcpApps = appId
      ? [appId]
      : stringList(previousMetadata.enabledMcpApps);
    const mergedMetadata = {
      ...previousMetadata,
      ...(identity.metadata ?? {}),
      ...(enabledMcpApps.length > 0 ? { enabledMcpApps } : {}),
    };
    const connectionValues = {
      userId: oauthState.userId,
      appId: appId || null,
      provider: input.provider,
      authType:
        getIntegrationProvider(input.provider)?.authType ?? ("oauth2" as const),
      status: "connected" as const,
      displayName: identity.displayName,
      externalAccountId: identity.externalAccountId,
      scopes: effectiveScopes,
      capabilities: appId
        ? (getIntegrationMcpApp(appId)?.capabilities ?? [])
        : (getIntegrationProvider(input.provider)?.capabilities ?? []),
      metadata: mergedMetadata,
      lastSyncedAt: new Date(),
      updatedAt: new Date(),
    };
    const connectionRows = existingConnectionRows[0]
      ? await tx
          .update(integrationConnections)
          .set(connectionValues)
          .where(eq(integrationConnections.id, existingConnectionRows[0].id))
          .returning()
      : appId
        ? await tx
            .insert(integrationConnections)
            .values(connectionValues)
            .onConflictDoUpdate({
              target: [
                integrationConnections.userId,
                integrationConnections.appId,
              ],
              set: connectionValues,
            })
            .returning()
        : await tx
            .insert(integrationConnections)
            .values(connectionValues)
            .returning();
    const nextConnection = connectionRows[0];
    if (!nextConnection) {
      throw badRequest("OAuth connection could not be stored");
    }

    const existingCredentialRows = await tx
      .select({ encryptedPayload: integrationCredentials.encryptedPayload })
      .from(integrationCredentials)
      .where(eq(integrationCredentials.connectionId, nextConnection.id))
      .limit(1);
    let previousRefreshToken: string | null = null;
    if (existingCredentialRows[0]?.encryptedPayload) {
      try {
        previousRefreshToken = decryptJson<GoogleOAuthPayload>(
          app.config,
          existingCredentialRows[0].encryptedPayload,
        ).refreshToken;
      } catch {
        previousRefreshToken = null;
      }
    }
    const refreshToken =
      typeof tokenPayload.refresh_token === "string" &&
      tokenPayload.refresh_token
        ? tokenPayload.refresh_token
        : previousRefreshToken;
    const encryptedPayload = encryptJson(app.config, {
      accessToken,
      refreshToken,
      tokenType:
        typeof tokenPayload.token_type === "string"
          ? tokenPayload.token_type
          : "Bearer",
      scope: typeof tokenPayload.scope === "string" ? tokenPayload.scope : null,
      raw: tokenPayload,
    });
    const expiresAt = getExpiresAtFromTokenPayload(tokenPayload);

    await tx
      .insert(integrationCredentials)
      .values({
        connectionId: nextConnection.id,
        encryptedPayload,
        expiresAt,
      })
      .onConflictDoUpdate({
        target: integrationCredentials.connectionId,
        set: {
          encryptedPayload,
          expiresAt,
          updatedAt: new Date(),
        },
      });

    const completedStateRows = await tx
      .update(oauthStates)
      .set({ status: "completed", consumedAt: new Date() })
      .where(
        and(
          eq(oauthStates.id, oauthState.id),
          eq(oauthStates.status, "expired"),
        ),
      )
      .returning({ id: oauthStates.id });
    if (!completedStateRows[0]) {
      throw badRequest("OAuth state completion failed");
    }
    return nextConnection;
  });

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
      ...(appId ? { appId } : {}),
    },
  });

  return {
    redirectUri: oauthState.redirectUri,
    status: "connected" as const,
    provider: input.provider,
    appId: appId || undefined,
    connectionId: connection.id,
    // Route katmanındaki bağlantı-sonrası MCP probu için; redirect
    // query'sine ASLA yazılmaz.
    userId: oauthState.userId,
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
    .where(
      and(
        eq(integrationConnections.id, input.connectionId),
        eq(integrationConnections.userId, input.userId),
      ),
    )
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

export async function disconnectIntegrationApp(
  app: FastifyInstance,
  input: {
    userId: string;
    appId: string;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  const catalogEntry = getIntegrationMcpApp(input.appId);
  if (!catalogEntry) {
    throw notFound("Integration app not found");
  }
  const rows = await app.db
    .select()
    .from(integrationConnections)
    .where(
      and(
        eq(integrationConnections.userId, input.userId),
        eq(integrationConnections.appId, input.appId),
        eq(integrationConnections.status, "connected"),
      ),
    )
    .limit(1);
  const connection = rows[0];
  if (!connection) {
    throw notFound("Integration connection not found");
  }

  // Disconnect is fail-closed for providers that expose a revoke endpoint:
  // if revocation fails there, this throws and the local credential is kept so
  // the user can retry. Providers without a revoke endpoint return `false` and
  // are disconnected by deleting the local encrypted credential below.
  const remoteRevoked = await revokeProviderAuthorization(
    app,
    connection.id,
    catalogEntry.provider,
  );

  const metadata = {
    ...recordValue(connection.metadata),
    enabledMcpApps: [],
  };

  await app.db
    .update(integrationConnections)
    .set({ status: "revoked", metadata, updatedAt: new Date() })
    .where(eq(integrationConnections.id, connection.id));
  await app.db
    .delete(integrationCredentials)
    .where(eq(integrationCredentials.connectionId, connection.id));

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "integration.app.disconnect",
    resourceType: "integration_connection",
    resourceId: connection.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      provider: catalogEntry.provider,
      appId: input.appId,
      remoteRevoked,
    },
  });

  return {
    appId: input.appId,
    provider: catalogEntry.provider,
    connected: false,
    remainingApps: [],
  };
}

/**
 * MCP el sıkışma probu için token erişimi. Çağıran (mcp-probe) connection'ı
 * userId ile doğrulamış olmalı — bu fonksiyon connection-scoped token'ı
 * yeniler/döndürür, kullanıcı doğrulaması yapmaz.
 */
export async function getConnectionAccessTokenForProbe(
  app: FastifyInstance,
  connectionId: string,
  provider: ConnectionProvider,
  appId?: string,
  refreshTimeoutMs = 8_000,
) {
  return getConnectionAccessToken(
    app,
    connectionId,
    provider,
    appId,
    refreshTimeoutMs,
  );
}

async function getConnectionAccessToken(
  app: FastifyInstance,
  connectionId: string,
  provider: ConnectionProvider,
  appId?: string,
  refreshTimeoutMs = 12_000,
) {
  if (provider === "google") {
    return (
      await getGoogleMailAccessToken(app, connectionId, appId, refreshTimeoutMs)
    ).accessToken;
  }
  const { credential, tokenPayload } = await loadGoogleOAuthTokenPayload(
    app,
    connectionId,
  );
  if (
    credential.expiresAt &&
    credential.expiresAt.getTime() <= Date.now() + 30_000
  ) {
    if (!tokenPayload.refreshToken) {
      throw new AppError(400, "connector_auth_required", "Integration connection needs re-authentication");
    }
    return refreshProviderOAuthAccessToken(
      app,
      connectionId,
      provider,
      tokenPayload.refreshToken,
      appId,
      refreshTimeoutMs,
    );
  }
  if (!tokenPayload.accessToken) {
    throw badRequest("Integration access token is missing");
  }
  return tokenPayload.accessToken;
}

/**
 * Server-side connector access: find the user's connected integration that
 * grants a capability (gmail/calendar/drive/...) with all required scopes and
 * return a fresh access token. Used by brain connector tools so a mobile-only
 * user can read their integrations without a paired desktop. Throws a typed
 * badRequest/notFound if nothing usable is connected.
 */
export async function getConnectorAccessToken(
  app: FastifyInstance,
  input: {
    userId: string;
    capability: string;
    requiredScopes?: string[];
    acceptedScopeSets?: string[][];
    refreshTimeoutMs?: number;
  },
): Promise<{
  connectionId: string;
  provider: ConnectionProvider;
  accessToken: string;
}> {
  const rows = await app.db
    .select({
      id: integrationConnections.id,
      appId: integrationConnections.appId,
      provider: integrationConnections.provider,
      scopes: integrationConnections.scopes,
      capabilities: integrationConnections.capabilities,
      updatedAt: integrationConnections.updatedAt,
    })
    .from(integrationConnections)
    .where(
      and(
        eq(integrationConnections.userId, input.userId),
        eq(integrationConnections.status, "connected"),
      ),
    )
    .orderBy(desc(integrationConnections.updatedAt));

  const match = rows.find((row) => {
    const capabilities = Array.isArray(row.capabilities)
      ? row.capabilities.map((value) => String(value ?? "").trim())
      : [];
    if (!capabilities.includes(input.capability)) {
      return false;
    }
    if (!input.requiredScopes?.length) {
      return true;
    }
    const acceptedScopeSets = input.acceptedScopeSets?.length
      ? input.acceptedScopeSets
      : [input.requiredScopes];
    return acceptedScopeSets.some(
      (scopeSet) =>
        missingOauthScopes(row.provider, stringList(row.scopes), scopeSet)
          .length === 0,
    );
  });

  if (!match) {
    throw notFound(
      `No connected integration grants capability ${input.capability}`,
    );
  }

  const accessToken = await getConnectionAccessToken(
    app,
    match.id,
    match.provider,
    match.appId ?? undefined,
    input.refreshTimeoutMs ?? 8_000,
  );
  return { connectionId: match.id, provider: match.provider, accessToken };
}

/** Capabilities the user currently has connected with all required scopes. */
export async function listConnectedCapabilities(
  app: FastifyInstance,
  userId: string,
): Promise<string[]> {
  const grants = await listConnectedCapabilityGrants(app, userId);
  return [...new Set(grants.flatMap((grant) => grant.capabilities))];
}

export type RemoteMcpRequestResolution = {
  requestedCapabilities: string[];
  selection: RemoteMcpSelectionMetadata | null;
};

function normalizedMcpName(value: string): string {
  return value
    .toLocaleLowerCase("tr-TR")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function safeMcpMetadataDescription(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const description = (value as Record<string, unknown>).description;
  return typeof description === "string"
    ? description.replace(/\s+/g, " ").trim().slice(0, 320)
    : "";
}

function boundedMcpCapabilities(value: unknown, limit = 24): string[] {
  return [
    ...new Set(
      stringList(value)
        .map((capability) => capability.replace(/\s+/g, " ").trim().slice(0, 120))
        .filter(Boolean),
    ),
  ].slice(0, limit);
}

function normalizeSafePublicMcpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  try {
    const url = new URL(value.trim());
    const hostname = url.hostname.toLowerCase();
    const blockedHostSuffixes = [
      "localhost",
      ".localhost",
      ".local",
      ".internal",
      ".lan",
      ".home",
      ".test",
      ".invalid",
      ".example",
    ];
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      (url.port && url.port !== "443") ||
      !hostname.includes(".") ||
      isIP(hostname) !== 0 ||
      blockedHostSuffixes.some(
        (suffix) => hostname === suffix || hostname.endsWith(suffix),
      )
    ) {
      return null;
    }
    return url.toString();
  } catch {
    return null;
  }
}

export function normalizeRemoteMcpSelectionMetadata(
  value: unknown,
): RemoteMcpSelectionMetadata | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.targetKind !== "curated_app" && record.targetKind !== "mcp_server") {
    return null;
  }
  const clippedId = (candidate: unknown) =>
    typeof candidate === "string" && candidate.trim()
      ? candidate.trim().slice(0, 160)
      : null;
  const operation =
    record.operation === "read" || record.operation === "write"
      ? record.operation
      : "unknown";
  const allowedSources = new Set<RemoteMcpSelectionMetadata["source"]>([
    "semantic_transformer",
    "legacy_pattern",
    "explicit_name",
    "requested_capability",
  ]);
  const source = allowedSources.has(record.source as RemoteMcpSelectionMetadata["source"])
    ? (record.source as RemoteMcpSelectionMetadata["source"])
    : "requested_capability";
  const boundedNumber = (candidate: unknown) =>
    typeof candidate === "number" && Number.isFinite(candidate)
      ? Math.max(0, Math.min(1, candidate))
      : 0;
  const selection: RemoteMcpSelectionMetadata = {
    targetKind: record.targetKind,
    appId: clippedId(record.appId),
    connectionId: clippedId(record.connectionId),
    serverId: clippedId(record.serverId),
    operation,
    confidence: boundedNumber(record.confidence),
    margin: boundedNumber(record.margin),
    source,
  };
  if (selection.targetKind === "curated_app") {
    return selection.appId && selection.connectionId ? selection : null;
  }
  return selection.serverId ? selection : null;
}

/**
 * Resolve the target from current connection/server registries and retain the
 * bounded evidence needed by routing and the desktop work order. No MCP config,
 * credential, URL or token crosses this metadata boundary.
 */
export async function resolveRemoteMcpRequest(
  app: FastifyInstance,
  input: {
    userId: string;
    prompt: string;
    requestedCapabilities: string[];
  },
): Promise<RemoteMcpRequestResolution> {
  const requestedCapabilities = [...new Set(input.requestedCapabilities)];
  const remoteMcpCapabilities = new Set(
    integrationMcpAppCatalog
      .filter((entry) => entry.execution === "remote_mcp")
      .flatMap((entry) => entry.capabilities),
  );
  const connectionQuery = app.db
      .select({
        id: integrationConnections.id,
        appId: integrationConnections.appId,
        provider: integrationConnections.provider,
        capabilities: integrationConnections.capabilities,
      })
      .from(integrationConnections)
      .where(
        and(
          eq(integrationConnections.userId, input.userId),
          eq(integrationConnections.status, "connected"),
        ),
      );
  const registeredServerQuery = app.db
      .select({
        id: mcpServers.id,
        integrationConnectionId: mcpServers.integrationConnectionId,
        name: mcpServers.name,
        transport: mcpServers.transport,
        status: mcpServers.status,
        authType: mcpServers.authType,
        baseUrl: mcpServers.baseUrl,
        command: mcpServers.command,
        capabilities: mcpServers.capabilities,
        metadata: mcpServers.metadata,
      })
      .from(mcpServers)
      .where(eq(mcpServers.userId, input.userId));
  const [connections, registeredServers] = await Promise.all([
    Promise.resolve(connectionQuery).catch(() => []),
    Promise.resolve(registeredServerQuery).catch(() => []),
  ]);
  const connectedCapabilities = new Set(
    connections.flatMap((connection) => stringList(connection.capabilities)),
  );
  const connectedRemoteMcpCapabilities = [...connectedCapabilities].filter(
    (capability) => remoteMcpCapabilities.has(capability),
  );

  const catalogSelection = connectedRemoteMcpCapabilities.length
    ? await inferRequestedRemoteMcpSelectionSemantic(
        input.prompt,
        connectedRemoteMcpCapabilities,
      ).catch(() => null)
    : null;
  if (catalogSelection) {
    const connection = connections.find(
      (candidate) =>
        candidate.appId === catalogSelection.entry.id &&
        candidate.provider === catalogSelection.entry.provider &&
        catalogSelection.entry.capabilities.some((capability) =>
          stringList(candidate.capabilities).includes(capability),
        ),
    );
    if (connection) {
      const operationResolved = catalogSelection.operation !== "unknown";
      return {
        requestedCapabilities:
          requestedCapabilities.includes("mcp_call_tool") || !operationResolved
            ? requestedCapabilities
            : [...requestedCapabilities, "mcp_call_tool"],
        selection: {
          targetKind: "curated_app",
          appId: catalogSelection.entry.id,
          connectionId: connection.id,
          serverId: null,
          operation: catalogSelection.operation,
          confidence: catalogSelection.confidence,
          margin: catalogSelection.margin,
          source: catalogSelection.source,
        },
      };
    }
  }

  // Generic registered servers become semantic candidates from their existing
  // name/capability/description fields. A row must be explicitly connected;
  // the default `configured` state is never execution authorization.
  const executableServers = registeredServers.filter(
    (server) =>
      server.status === "connected" &&
      ((server.transport === "stdio" && Boolean(server.command?.trim())) ||
        ((server.transport === "remote" ||
          server.transport === "streamable_http" ||
          server.transport === "oauth_remote") &&
          server.authType === "none" &&
          normalizeSafePublicMcpUrl(server.baseUrl) != null)),
  );
  const operation = executableServers.length
    ? await classifyConnectedDataOperationSemantic(input.prompt).catch(() => null)
    : null;
  if (operation) {
    const normalizedPrompt = ` ${normalizedMcpName(input.prompt)} `;
    const explicitlyNamed = executableServers.filter((server) => {
      const name = normalizedMcpName(server.name);
      return name.length >= 3 && normalizedPrompt.includes(` ${name} `);
    });
    let selected = explicitlyNamed.length === 1 ? explicitlyNamed[0] : null;
    let source: RemoteMcpSelectionMetadata["source"] = "explicit_name";
    let confidence = operation.confidence;
    let margin = operation.margin;
    if (!selected && explicitlyNamed.length === 0) {
      const target = await rankSemanticTextCandidates(
        input.prompt,
        executableServers.map((server) => ({
          id: server.id,
          description: [
            `Access the user's connected ${server.name} application through MCP.`,
            safeMcpMetadataDescription(server.metadata),
            boundedMcpCapabilities(server.capabilities, 16).join(", "),
          ]
            .filter(Boolean)
            .join(" "),
        })),
        {
          transformerMinScore: 0.68,
          transformerMinMargin: 0.03,
          hashMinScore: 1,
          hashMinMargin: 1,
        },
      ).catch(() => null);
      if (target?.source === "transformer") {
        selected = executableServers.find((server) => server.id === target.id) ?? null;
        source = "semantic_transformer";
        confidence = Math.min(confidence, target.score);
        margin = Math.min(margin, target.margin);
      }
    }
    if (selected) {
      return {
        requestedCapabilities: requestedCapabilities.includes("mcp_call_tool")
          ? requestedCapabilities
          : [...requestedCapabilities, "mcp_call_tool"],
        selection: {
          targetKind: "mcp_server",
          appId: null,
          connectionId: selected.integrationConnectionId ?? null,
          serverId: selected.id,
          operation: operation.operation,
          confidence,
          margin,
          source,
        },
      };
    }
  }

  return { requestedCapabilities, selection: null };
}

/** Backwards-compatible capability-only projection for existing callers. */
export async function resolveRemoteMcpRequestedCapabilities(
  app: FastifyInstance,
  input: {
    userId: string;
    prompt: string;
    requestedCapabilities: string[];
  },
): Promise<string[]> {
  return (await resolveRemoteMcpRequest(app, input)).requestedCapabilities;
}

export async function listConnectedCapabilityGrants(
  app: FastifyInstance,
  userId: string,
): Promise<
  Array<{
    provider: ConnectionProvider;
    scopes: string[];
    capabilities: string[];
  }>
> {
  const rows = await app.db
    .select({
      provider: integrationConnections.provider,
      scopes: integrationConnections.scopes,
      capabilities: integrationConnections.capabilities,
    })
    .from(integrationConnections)
    .where(
      and(
        eq(integrationConnections.userId, userId),
        eq(integrationConnections.status, "connected"),
      ),
    );
  return rows
    .map((row) => ({
      provider: row.provider,
      scopes: stringList(row.scopes),
      capabilities: stringList(row.capabilities),
    }))
    .filter((row) => row.capabilities.length > 0);
}

export async function listRuntimeMcpConnections(
  app: FastifyInstance,
  userId: string,
) {
  const runtimeTokenRefreshTimeoutMs = 4_000;
  const [rows, registeredMcpServers] = await Promise.all([
    app.db
      .select({
        id: integrationConnections.id,
        appId: integrationConnections.appId,
        provider: integrationConnections.provider,
        status: integrationConnections.status,
        displayName: integrationConnections.displayName,
        scopes: integrationConnections.scopes,
        capabilities: integrationConnections.capabilities,
        metadata: integrationConnections.metadata,
        updatedAt: integrationConnections.updatedAt,
      })
      .from(integrationConnections)
      .where(
        and(
          eq(integrationConnections.userId, userId),
          eq(integrationConnections.status, "connected"),
        ),
      ),
    // mcp_servers used to be CRUD-only. Read only the minimum lease fields;
    // config/metadata/env and every stored credential stay out.
    app.db
      .select({
        id: mcpServers.id,
        integrationConnectionId: mcpServers.integrationConnectionId,
        name: mcpServers.name,
        transport: mcpServers.transport,
        authType: mcpServers.authType,
        status: mcpServers.status,
        baseUrl: mcpServers.baseUrl,
        command: mcpServers.command,
        args: mcpServers.args,
        capabilities: mcpServers.capabilities,
        updatedAt: mcpServers.updatedAt,
      })
      .from(mcpServers)
      .where(eq(mcpServers.userId, userId)),
  ]);

  const candidates = rows
    .flatMap((connection) => {
      return integrationMcpAppCatalog
        .filter(
          (entry) =>
            entry.id === connection.appId &&
            entry.provider === connection.provider &&
            // Only real remote MCP servers are leased to the desktop runtime.
            // server_connector capabilities (Gmail/Drive/Calendar) are served by
            // the shared brain's REST connector tools, so they never need — and
            // must not advertise — a remote MCP URL to the desktop.
            entry.execution === "remote_mcp" &&
            (entry.authStrategy === "provider_bearer" ||
              entry.authStrategy === "mcp_oauth") &&
            entry.stage !== "setup_required" &&
            missingOauthScopes(
              entry.provider,
              stringList(connection.scopes),
              entry.oauthScopes,
            ).length === 0,
        )
        .map((entry) => ({ connection, entry }));
    })
    .sort(
      (left, right) =>
        left.entry.id.localeCompare(right.entry.id) ||
        left.connection.id.localeCompare(right.connection.id),
    );

  const curatedServers = await Promise.all(
    candidates.map(async ({ connection, entry }) => {
      let accessToken = "";
      let authErrorCode = "";
      try {
        accessToken = await getConnectionAccessToken(
          app,
          connection.id,
          connection.provider,
          connection.appId ?? undefined,
          runtimeTokenRefreshTimeoutMs,
        );
      } catch {
        authErrorCode = "MCP_AUTH_REQUIRED";
      }

      // El sıkışma probu: "connected" yalnız OAuth başarısı; sunucunun gerçekten
      // konuştuğunu son prob söyler. Prob başarısızsa lease'te disabled taşınır —
      // desktop bağlanmayı denemez, mobil "yeniden bağlan" gösterebilir.
      const probe = readConnectionMcpProbe(connection.metadata, entry.id);
      const probeFresh = probe ? isConnectionMcpProbeFresh(probe) : false;
      if (
        !authErrorCode &&
        probe?.status === "failed" &&
        probe.errorCode === "MCP_AUTH_REQUIRED"
      ) {
        authErrorCode = "MCP_AUTH_REQUIRED";
      }
      const freshTransientFailure = Boolean(
        probeFresh &&
          probe?.status === "failed" &&
          probe.errorCode !== "MCP_AUTH_REQUIRED",
      );

      return {
        id: `app_${entry.id}`,
        appId: entry.id,
        connectionId: connection.id,
        provider: entry.provider,
        name: entry.displayName,
        transport: "streamable_http",
        url: entry.serverUrl,
        authType: "bearer",
        accessToken,
        authErrorCode,
        catalogSource: "integration_catalog" as const,
        // Auth failures always fail closed. A transient failed probe disables
        // only until its TTL; after expiry runtime may reconnect and self-heal.
        enabled: !authErrorCode && !freshTransientFailure,
        probeStatus:
          probe?.status === "failed" && !probeFresh
            ? "stale"
            : (probe?.status ?? "unknown"),
        probeFresh,
        probedAt: probe?.probedAt ?? null,
        probeExpiresAt: probe?.expiresAt ?? null,
        probeErrorCode: probe?.errorCode ?? null,
        probeToolCount: probe?.toolCount ?? null,
        probeToolCatalogDigest: probe?.toolCatalogDigest ?? null,
        probeToolNames: probe?.toolNames?.slice(0, 24) ?? [],
        startupTimeoutSec: 15,
        callTimeoutSec: 45,
      };
    }),
  );

  const registeredStdioServers = registeredMcpServers
    .filter(
      (server) =>
        server.status === "connected" &&
        server.transport === "stdio" &&
        Boolean(server.command?.trim()),
    )
    .map((server) => ({
      id: server.id,
      appId: null,
      connectionId: server.integrationConnectionId,
      provider: null,
      name: String(server.name ?? "MCP server").slice(0, 160),
      transport: "stdio" as const,
      command: server.command!.trim().slice(0, 512),
      args: stringList(server.args)
        .slice(0, 32)
        .map((argument) => argument.slice(0, 512)),
      enabled: true,
      catalogSource: "mcp_servers" as const,
      registeredCapabilities: boundedMcpCapabilities(server.capabilities),
      startupTimeoutSec: 15,
      callTimeoutSec: 45,
    }));
  const registeredRemoteServers = registeredMcpServers.flatMap((server) => {
    if (
      server.status !== "connected" ||
      (server.transport !== "remote" &&
        server.transport !== "streamable_http" &&
        server.transport !== "oauth_remote") ||
      server.authType !== "none"
    ) {
      return [];
    }
    const safeUrl = normalizeSafePublicMcpUrl(server.baseUrl);
    if (!safeUrl) return [];
    return [
      {
        id: server.id,
        appId: null,
        connectionId: server.integrationConnectionId,
        provider: null,
        name: String(server.name ?? "MCP server").slice(0, 160),
        transport: "streamable_http" as const,
        url: safeUrl,
        authType: "none" as const,
        accessToken: "",
        authErrorCode: "",
        enabled: true,
        catalogSource: "mcp_servers" as const,
        registeredCapabilities: boundedMcpCapabilities(server.capabilities),
        startupTimeoutSec: 15,
        callTimeoutSec: 45,
      },
    ];
  });
  const servers = [
    ...curatedServers,
    ...registeredStdioServers,
    ...registeredRemoteServers,
  ];
  const leasedRegisteredIds = new Set(
    [...registeredStdioServers, ...registeredRemoteServers].map(
      (server) => server.id,
    ),
  );
  const unavailableServers = registeredMcpServers
    .filter((server) => !leasedRegisteredIds.has(server.id))
    .map((server) => ({
      id: server.id,
      name: String(server.name ?? "MCP server").slice(0, 160),
      status: server.status,
      transport: server.transport,
      reason:
        server.status !== "connected"
          ? "not_active"
          : server.authType !== "none"
            ? "auth_secret_not_leasable"
            : (server.transport === "remote" ||
                  server.transport === "streamable_http" ||
                  server.transport === "oauth_remote") &&
                !normalizeSafePublicMcpUrl(server.baseUrl)
              ? "unsafe_remote_url"
            : "transport_not_leasable",
    }));

  const revision = createHash("sha256")
    .update(
      JSON.stringify(
        {
          connections: rows.map((connection) => ({
            id: connection.id,
            appId: connection.appId,
            status: connection.status,
            updatedAt: connection.updatedAt.toISOString(),
          })),
          registeredServers: registeredMcpServers.map((server) => ({
            id: server.id,
            status: server.status,
            transport: server.transport,
            updatedAt: server.updatedAt.toISOString(),
          })),
        },
      ),
    )
    .digest("hex");
  return { servers, unavailableServers, revision };
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
  const scopes = Array.isArray(connection.scopes)
    ? connection.scopes.map((value) => String(value ?? "").trim())
    : [];
  if (!scopes.includes("https://www.googleapis.com/auth/gmail.send")) {
    throw badRequest("Google Gmail send scope is missing");
  }

  const token = await getGoogleMailAccessToken(
    app,
    connection.id,
    connection.appId ?? undefined,
  );
  const mimeMessage = buildEmailMimeMessage({
    from: connection.displayName || "Elyan",
    to: input.to,
    cc: input.cc,
    bcc: input.bcc,
    replyTo: input.replyTo,
    subject: input.subject,
    body: input.body,
  });

  const response = await fetch(
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
    {
      signal: AbortSignal.timeout(15_000),
      method: "POST",
      headers: {
        Authorization: `Bearer ${token.accessToken}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        raw: Buffer.from(mimeMessage, "utf8").toString("base64url"),
      }),
    },
  );
  const payload = (await parseJsonResponse(response)) as Record<
    string,
    unknown
  >;
  if (!response.ok || payload.error) {
    throw badRequest("Gmail message send failed", payload);
  }

  const messageId = typeof payload.id === "string" ? payload.id : "";
  const threadId = typeof payload.threadId === "string" ? payload.threadId : "";
  const labelIds = Array.isArray(payload.labelIds)
    ? payload.labelIds
        .map((value) => String(value ?? "").trim())
        .filter(Boolean)
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
