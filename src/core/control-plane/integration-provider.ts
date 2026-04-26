import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'crypto';
import { z } from 'zod';
import { env } from '@/lib/env';
import {
  ControlPlaneConfigurationError,
  ControlPlaneProviderError,
} from './errors';
import {
  controlPlaneIntegrationProviderSchema,
  type ControlPlaneIntegration,
  type ControlPlaneIntegrationProvider,
} from './types';

type ProviderConfig = {
  provider: ControlPlaneIntegrationProvider;
  displayName: string;
  authorizationEndpoint: string;
  tokenEndpoint: string;
  userInfoEndpoint: string;
  defaultScopes: string[];
  surfaces: Array<'gmail' | 'calendar' | 'github' | 'notion'>;
  clientId?: string;
  clientSecret?: string;
  supportsRefreshTokens: boolean;
};

const oauthTokenResponseSchema = z.object({
  access_token: z.string().min(1),
  refresh_token: z.string().min(1).optional(),
  id_token: z.string().min(1).optional(),
  expires_in: z.number().int().positive().optional(),
  scope: z.string().optional(),
  token_type: z.string().optional(),
});

const googleProfileSchema = z.object({
  sub: z.string().min(1),
  email: z.string().email().optional(),
  name: z.string().min(1).optional(),
});

const PROVIDERS: Record<ControlPlaneIntegrationProvider, ProviderConfig> = {
  google: {
    provider: 'google',
    displayName: 'Google Workspace',
    authorizationEndpoint: 'https://accounts.google.com/o/oauth2/v2/auth',
    tokenEndpoint: 'https://oauth2.googleapis.com/token',
    userInfoEndpoint: 'https://openidconnect.googleapis.com/v1/userinfo',
    defaultScopes: [
      'openid',
      'email',
      'profile',
      'https://www.googleapis.com/auth/gmail.modify',
      'https://www.googleapis.com/auth/calendar.events',
    ],
    surfaces: ['gmail', 'calendar'],
    clientId: env.GOOGLE_CLIENT_ID,
    clientSecret: env.GOOGLE_CLIENT_SECRET,
    supportsRefreshTokens: true,
  },
  github: {
    provider: 'github',
    displayName: 'GitHub',
    authorizationEndpoint: 'https://github.com/login/oauth/authorize',
    tokenEndpoint: 'https://github.com/login/oauth/access_token',
    userInfoEndpoint: 'https://api.github.com/user',
    defaultScopes: ['read:user', 'user:email', 'repo'],
    surfaces: ['github'],
    clientId: env.GITHUB_CLIENT_ID,
    clientSecret: env.GITHUB_CLIENT_SECRET,
    supportsRefreshTokens: true,
  },
  notion: {
    provider: 'notion',
    displayName: 'Notion',
    authorizationEndpoint: 'https://api.notion.com/v1/oauth/authorize',
    tokenEndpoint: 'https://api.notion.com/v1/oauth/token',
    userInfoEndpoint: 'https://api.notion.com/v1/users/me',
    defaultScopes: ['read_content', 'insert_content', 'update_content', 'read_user_info'],
    surfaces: ['notion'],
    clientId: env.NOTION_CLIENT_ID,
    clientSecret: env.NOTION_CLIENT_SECRET,
    supportsRefreshTokens: true,
  },
};

function getSecretKey() {
  if (!env.NEXTAUTH_SECRET) {
    throw new ControlPlaneConfigurationError('NEXTAUTH_SECRET is required for OAuth token protection');
  }

  return createHash('sha256').update(env.NEXTAUTH_SECRET).digest();
}

function toBase64Url(value: Buffer) {
  return value.toString('base64url');
}

function fromBase64Url(value: string) {
  return Buffer.from(value, 'base64url');
}

export function getIntegrationProviderConfig(provider: ControlPlaneIntegrationProvider) {
  const parsed = controlPlaneIntegrationProviderSchema.parse(provider);
  return PROVIDERS[parsed];
}

export function isIntegrationProviderConfigured(provider: ControlPlaneIntegrationProvider) {
  const config = getIntegrationProviderConfig(provider);
  return Boolean(config.clientId && config.clientSecret && env.NEXTAUTH_SECRET);
}

export function buildIntegrationAuthorizationUrl(
  provider: ControlPlaneIntegrationProvider,
  input: {
    redirectUri: string;
    state: string;
    codeChallenge: string;
    scopes?: string[];
  }
) {
  const config = getIntegrationProviderConfig(provider);
  if (!config.clientId) {
    throw new ControlPlaneConfigurationError(`${config.displayName} client id is not configured`);
  }

  const url = new URL(config.authorizationEndpoint);
  const scopes = input.scopes?.length ? input.scopes : config.defaultScopes;
  url.searchParams.set('client_id', config.clientId);
  url.searchParams.set('redirect_uri', input.redirectUri);
  url.searchParams.set('response_type', 'code');
  url.searchParams.set('scope', scopes.join(provider === 'google' ? ' ' : ' '));
  url.searchParams.set('state', input.state);
  url.searchParams.set('code_challenge', input.codeChallenge);
  url.searchParams.set('code_challenge_method', 'S256');

  if (provider === 'google') {
    url.searchParams.set('access_type', 'offline');
    url.searchParams.set('prompt', 'consent');
    url.searchParams.set('include_granted_scopes', 'true');
  }

  if (provider === 'github') {
    url.searchParams.set('allow_signup', 'false');
  }

  if (provider === 'notion') {
    url.searchParams.set('owner', 'user');
  }

  return url.toString();
}

function buildTokenRequestBody(
  provider: ControlPlaneIntegrationProvider,
  input: {
    code: string;
    redirectUri: string;
    codeVerifier: string;
    refreshToken?: string;
  }
) {
  const config = getIntegrationProviderConfig(provider);
  if (!config.clientId || !config.clientSecret) {
    throw new ControlPlaneConfigurationError(`${config.displayName} OAuth is not configured`);
  }

  const body = new URLSearchParams();
  body.set('client_id', config.clientId);
  body.set('client_secret', config.clientSecret);
  body.set('redirect_uri', input.redirectUri);

  if (input.refreshToken) {
    body.set('grant_type', 'refresh_token');
    body.set('refresh_token', input.refreshToken);
    return body;
  }

  body.set('grant_type', 'authorization_code');
  body.set('code', input.code);
  body.set('code_verifier', input.codeVerifier);
  return body;
}

async function parseTokenResponse(response: Response) {
  const payload = await response.json().catch(() => null);
  const parsed = oauthTokenResponseSchema.safeParse(payload);

  if (!parsed.success) {
    const body = typeof payload === 'object' && payload ? JSON.stringify(payload) : 'unknown token response';
    throw new ControlPlaneProviderError(`OAuth token response was invalid: ${body}`);
  }

  return parsed.data;
}

export async function exchangeOAuthCode(
  provider: ControlPlaneIntegrationProvider,
  input: {
    code: string;
    redirectUri: string;
    codeVerifier: string;
  }
) {
  const config = getIntegrationProviderConfig(provider);
  if (!config.clientId || !config.clientSecret) {
    throw new ControlPlaneConfigurationError(`${config.displayName} OAuth is not configured`);
  }

  const response = await fetch(config.tokenEndpoint, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': provider === 'notion' ? 'application/json' : 'application/x-www-form-urlencoded',
    },
    body:
      provider === 'notion'
        ? JSON.stringify({
            grant_type: 'authorization_code',
            code: input.code,
            redirect_uri: input.redirectUri,
            client_id: config.clientId,
            client_secret: config.clientSecret,
            code_verifier: input.codeVerifier,
          })
        : buildTokenRequestBody(provider, input),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new ControlPlaneProviderError(`OAuth code exchange failed for ${config.displayName}: ${text || response.status}`);
  }

  return parseTokenResponse(response);
}

export async function refreshOAuthToken(
  provider: ControlPlaneIntegrationProvider,
  input: {
    refreshToken: string;
    redirectUri: string;
  }
) {
  const config = getIntegrationProviderConfig(provider);
  if (!config.clientId || !config.clientSecret) {
    throw new ControlPlaneConfigurationError(`${config.displayName} OAuth is not configured`);
  }

  const response = await fetch(config.tokenEndpoint, {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': provider === 'notion' ? 'application/json' : 'application/x-www-form-urlencoded',
    },
    body:
      provider === 'notion'
        ? JSON.stringify({
            grant_type: 'refresh_token',
            refresh_token: input.refreshToken,
            redirect_uri: input.redirectUri,
            client_id: config.clientId,
            client_secret: config.clientSecret,
          })
        : buildTokenRequestBody(provider, {
            code: '',
            redirectUri: input.redirectUri,
            codeVerifier: '',
            refreshToken: input.refreshToken,
          }),
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new ControlPlaneProviderError(`OAuth refresh failed for ${config.displayName}: ${text || response.status}`);
  }

  return parseTokenResponse(response);
}

export function encryptIntegrationSecret(value: string) {
  const key = getSecretKey();
  const iv = randomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([cipher.update(value, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `v1.${toBase64Url(iv)}.${toBase64Url(encrypted)}.${toBase64Url(tag)}`;
}

export function decryptIntegrationSecret(value: string) {
  const [version, ivPart, encryptedPart, tagPart] = value.split('.');
  if (version !== 'v1' || !ivPart || !encryptedPart || !tagPart) {
    throw new ControlPlaneProviderError('Integration secret payload is invalid');
  }

  const key = getSecretKey();
  const decipher = createDecipheriv('aes-256-gcm', key, fromBase64Url(ivPart));
  decipher.setAuthTag(fromBase64Url(tagPart));
  const decrypted = Buffer.concat([
    decipher.update(fromBase64Url(encryptedPart)),
    decipher.final(),
  ]);
  return decrypted.toString('utf8');
}

function normalizeIntegrationProfile(provider: ControlPlaneIntegrationProvider, payload: unknown) {
  if (provider === 'google') {
    const parsed = googleProfileSchema.parse(payload);
    return {
      externalAccountId: parsed.sub,
      externalAccountLabel: parsed.name ?? parsed.email ?? parsed.sub,
      email: parsed.email,
      metadata: {
        name: parsed.name,
      },
    };
  }

  if (provider === 'github') {
    const parsed = z
      .object({
        id: z.union([z.string(), z.number()]).transform((value) => String(value)),
        login: z.string().min(1).optional(),
        name: z.string().min(1).nullable().optional(),
        email: z.string().email().nullable().optional(),
      })
      .parse(payload);
    return {
      externalAccountId: parsed.id,
      externalAccountLabel: parsed.name ?? parsed.login ?? parsed.email ?? parsed.id,
      email: parsed.email ?? undefined,
      metadata: {
        login: parsed.login,
      },
    };
  }

  const parsed = z
    .object({
      id: z.string().min(1),
      name: z.string().min(1).optional(),
      person: z
        .object({
          email: z.string().email().optional(),
        })
        .optional(),
    })
    .parse(payload);

  return {
    externalAccountId: parsed.id,
    externalAccountLabel: parsed.name ?? parsed.person?.email ?? parsed.id,
    email: parsed.person?.email,
    metadata: {},
  };
}

export async function fetchIntegrationProfile(
  provider: ControlPlaneIntegrationProvider,
  accessToken: string
) {
  const config = getIntegrationProviderConfig(provider);
  const response = await fetch(config.userInfoEndpoint, {
    headers:
      provider === 'notion'
        ? {
            Authorization: `Bearer ${accessToken}`,
            'Notion-Version': '2022-06-28',
            Accept: 'application/json',
          }
        : provider === 'github'
          ? {
              Authorization: `Bearer ${accessToken}`,
              Accept: 'application/vnd.github+json',
              'X-GitHub-Api-Version': '2022-11-28',
            }
          : {
              Authorization: `Bearer ${accessToken}`,
              Accept: 'application/json',
            },
  });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    throw new ControlPlaneProviderError(`Unable to load ${config.displayName} profile: ${text || response.status}`);
  }

  const payload = await response.json().catch(() => null);
  return normalizeIntegrationProfile(provider, payload);
}

export function buildIntegrationRedirectUri(provider: ControlPlaneIntegrationProvider) {
  return `${env.NEXTAUTH_URL ?? 'http://localhost:3000'}/api/control-plane/integrations/${provider}/callback`;
}

export function buildIntegrationAuthorizationContext(
  provider: ControlPlaneIntegrationProvider,
  input: {
    accountId: string;
    userId: string;
    returnTo?: string;
    state: string;
    codeVerifier: string;
  }
) {
  const config = getIntegrationProviderConfig(provider);
  const redirectUri = buildIntegrationRedirectUri(provider);
  const authorizationUrl = buildIntegrationAuthorizationUrl(provider, {
    redirectUri,
    state: input.state,
    codeChallenge: createHash('sha256').update(input.codeVerifier).digest('base64url'),
  });

  return {
    provider,
    displayName: config.displayName,
    redirectUri,
    authorizationUrl,
    state: input.state,
    codeVerifier: input.codeVerifier,
    accountId: input.accountId,
    userId: input.userId,
    returnTo: input.returnTo,
  };
}

export function createIntegrationIntegrationKey(integration: ControlPlaneIntegration) {
  return `${integration.provider}:${integration.accountId}:${integration.integrationId}`;
}
