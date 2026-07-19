import {
  discoverAuthorizationServerMetadata,
  discoverOAuthProtectedResourceMetadata,
  exchangeAuthorization,
  refreshAuthorization,
  registerClient,
  startAuthorization,
} from "@modelcontextprotocol/sdk/client/auth.js";
import type {
  AuthorizationServerMetadata,
  OAuthClientInformationFull,
  OAuthClientMetadata,
  OAuthProtectedResourceMetadata,
  OAuthTokens,
} from "@modelcontextprotocol/sdk/shared/auth.js";

/**
 * MCP OAuth (RFC 9728 protected-resource discovery + RFC 7591 dynamic client
 * registration + RFC 7636 PKCE authorization code flow) built on the official
 * SDK primitives. Stateless helpers only: token persistence, redirect handling
 * and the integration-connection wiring are the caller's responsibility and are
 * introduced separately once `ELYAN_MCP_SDK_ENABLED` is validated.
 *
 * This is the path that lifts Notion/GitHub/Slack out of `setup_required`.
 */

export type McpOAuthDiscovery = {
  protectedResource: OAuthProtectedResourceMetadata;
  authorizationServer: AuthorizationServerMetadata;
  authorizationServerUrl: string;
};

/**
 * RFC 9728: from an MCP server URL, discover the protected-resource metadata,
 * pick its first authorization server, and fetch that server's metadata.
 */
export async function discoverMcpOAuth(
  serverUrl: string,
  options: { resourceMetadataUrl?: string | URL } = {},
): Promise<McpOAuthDiscovery> {
  const protectedResource = await discoverOAuthProtectedResourceMetadata(
    serverUrl,
    { resourceMetadataUrl: options.resourceMetadataUrl },
  );
  const authorizationServerUrl = protectedResource.authorization_servers?.[0];
  if (!authorizationServerUrl) {
    throw new Error("mcp_oauth_no_authorization_server");
  }
  const authorizationServer = await discoverAuthorizationServerMetadata(
    authorizationServerUrl,
  );
  if (!authorizationServer) {
    throw new Error("mcp_oauth_metadata_unavailable");
  }
  return { protectedResource, authorizationServer, authorizationServerUrl };
}

/** RFC 7591: dynamically register an OAuth client with the authorization server. */
export async function registerMcpOAuthClient(input: {
  authorizationServerUrl: string;
  authorizationServer?: AuthorizationServerMetadata;
  clientMetadata: OAuthClientMetadata;
  scope?: string;
}): Promise<OAuthClientInformationFull> {
  return registerClient(input.authorizationServerUrl, {
    metadata: input.authorizationServer,
    clientMetadata: input.clientMetadata,
    scope: input.scope,
  });
}

export type McpAuthorizationStart = {
  authorizationUrl: URL;
  codeVerifier: string;
};

/**
 * RFC 7636: build the PKCE authorization URL and code verifier. The caller must
 * persist `codeVerifier` (bound to `state`) until the redirect returns.
 */
export async function beginMcpAuthorization(input: {
  authorizationServerUrl: string;
  authorizationServer?: AuthorizationServerMetadata;
  clientInformation: OAuthClientInformationFull;
  redirectUrl: string | URL;
  scope?: string;
  state?: string;
  resource?: URL;
}): Promise<McpAuthorizationStart> {
  return startAuthorization(input.authorizationServerUrl, {
    metadata: input.authorizationServer,
    clientInformation: input.clientInformation,
    redirectUrl: input.redirectUrl,
    scope: input.scope,
    state: input.state,
    resource: input.resource,
  });
}

/** Exchange an authorization code (plus stored PKCE verifier) for tokens. */
export async function completeMcpAuthorization(input: {
  authorizationServerUrl: string;
  authorizationServer?: AuthorizationServerMetadata;
  clientInformation: OAuthClientInformationFull;
  authorizationCode: string;
  codeVerifier: string;
  redirectUri: string | URL;
  resource?: URL;
}): Promise<OAuthTokens> {
  return exchangeAuthorization(input.authorizationServerUrl, {
    metadata: input.authorizationServer,
    clientInformation: input.clientInformation,
    authorizationCode: input.authorizationCode,
    codeVerifier: input.codeVerifier,
    redirectUri: input.redirectUri,
    resource: input.resource,
  });
}

/** Refresh access tokens; preserves the refresh token if the server omits one. */
export async function refreshMcpAuthorization(input: {
  authorizationServerUrl: string;
  authorizationServer?: AuthorizationServerMetadata;
  clientInformation: OAuthClientInformationFull;
  refreshToken: string;
  resource?: URL;
}): Promise<OAuthTokens> {
  return refreshAuthorization(input.authorizationServerUrl, {
    metadata: input.authorizationServer,
    clientInformation: input.clientInformation,
    refreshToken: input.refreshToken,
    resource: input.resource,
  });
}
