import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mockSession = {
  sub: 'usr_1',
  email: 'ayla@example.com',
  name: 'Ayla',
  accountId: 'acct_1',
  ownerType: 'individual',
  role: 'owner',
  planId: 'cloud_assisted',
};

const mockService = {
  beginIntegrationConnection: vi.fn(),
  completeIntegrationConnection: vi.fn(),
  disconnectIntegration: vi.fn(),
  executeIntegrationAction: vi.fn(),
  listIntegrations: vi.fn(),
};

vi.mock('@/core/control-plane', () => ({
  getControlPlaneService: vi.fn(() => mockService),
}));

vi.mock('@/core/control-plane/session', () => ({
  requireControlPlaneSession: vi.fn(async () => mockSession),
}));

vi.mock('@/core/control-plane/integration-provider', () => ({
  buildIntegrationAuthorizationContext: vi.fn((provider: string) => ({
    provider,
    displayName: provider,
    redirectUri: `https://elyan.dev/api/control-plane/integrations/${provider}/callback`,
    authorizationUrl: `https://auth.example.com/${provider}`,
    state: 'state-123',
    codeVerifier: 'verifier-123',
    accountId: mockSession.accountId,
    userId: mockSession.sub,
    returnTo: '/manage#manage-integrations',
  })),
  decryptIntegrationSecret: vi.fn(() =>
    JSON.stringify({
      provider: 'google',
      accountId: 'acct_1',
      userId: 'usr_1',
      returnTo: '/manage#manage-integrations',
      state: 'state-123',
      codeVerifier: 'verifier-123',
    })
  ),
  encryptIntegrationSecret: vi.fn(() => 'encrypted-cookie'),
  getIntegrationProviderConfig: vi.fn((provider: string) => ({
    provider,
    displayName: provider,
    authorizationEndpoint: `https://auth.example.com/${provider}`,
    tokenEndpoint: `https://token.example.com/${provider}`,
    userInfoEndpoint: `https://profile.example.com/${provider}`,
    defaultScopes: [],
    surfaces: [],
    clientId: 'client-id',
    clientSecret: 'client-secret',
    supportsRefreshTokens: true,
  })),
  isIntegrationProviderConfigured: vi.fn(() => true),
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe('control-plane integration routes', () => {
  it('starts OAuth linking with a redirect and state cookie', async () => {
    mockService.beginIntegrationConnection.mockResolvedValue({
      integrationId: 'int_1',
    });

    const { GET } = await import('@/app/api/control-plane/integrations/[integrationId]/connect/route');
    const request = new NextRequest(
      'http://127.0.0.1:3000/api/control-plane/integrations/google/connect?returnTo=/manage#manage-integrations',
      { method: 'GET' }
    );

    const response = await GET(request, { params: Promise.resolve({ integrationId: 'google' }) });

    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toBe('https://auth.example.com/google');
    expect(response.headers.get('set-cookie')).toContain('elyan.integration.oauth=');
    expect(mockService.beginIntegrationConnection).toHaveBeenCalledWith(
      'acct_1',
      'usr_1',
      expect.objectContaining({
        provider: 'google',
        state: expect.any(String),
        returnTo: '/manage',
        authorizationUrl: 'https://auth.example.com/google',
      })
    );
  });

  it('completes OAuth linking and redirects back to the manage surface', async () => {
    mockService.completeIntegrationConnection.mockResolvedValue({
      integration: {
        integrationId: 'int_1',
        provider: 'google',
        status: 'connected',
      },
    });

    const { GET } = await import('@/app/api/control-plane/integrations/[integrationId]/callback/route');
    const request = new NextRequest(
      'http://127.0.0.1:3000/api/control-plane/integrations/google/callback?code=auth-code&state=state-123',
      {
        method: 'GET',
        headers: {
          cookie: 'elyan.integration.oauth=encrypted-cookie',
        },
      }
    );

    const response = await GET(request, { params: Promise.resolve({ integrationId: 'google' }) });

    expect(response.status).toBe(307);
    expect(response.headers.get('location')).toContain('/manage?integration=google&status=connected');
    expect(mockService.completeIntegrationConnection).toHaveBeenCalledWith(
      expect.objectContaining({
        provider: 'google',
        accountId: 'acct_1',
        userId: 'usr_1',
        code: 'auth-code',
        state: 'state-123',
        codeVerifier: 'verifier-123',
      })
    );
  });

  it('executes a connected app action through the service', async () => {
    mockService.executeIntegrationAction.mockResolvedValue({
      ok: true,
      integration: {
        integrationId: 'int_1',
        provider: 'google',
        status: 'connected',
      },
      result: {
        kind: 'gmail.listMessages',
        messages: [],
      },
    });

    const { POST } = await import('@/app/api/control-plane/integrations/actions/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/control-plane/integrations/actions', {
      method: 'POST',
      body: JSON.stringify({
        provider: 'google',
        integrationId: 'int_1',
        action: 'gmail.listMessages',
        parameters: { maxResults: 3 },
      }),
      headers: {
        'content-type': 'application/json',
      },
    });

    const response = await POST(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(payload.result.kind).toBe('gmail.listMessages');
    expect(mockService.executeIntegrationAction).toHaveBeenCalledWith(
      'acct_1',
      expect.objectContaining({
        provider: 'google',
        integrationId: 'int_1',
        action: 'gmail.listMessages',
      })
    );
  });

  it('disconnects an integration cleanly', async () => {
    mockService.disconnectIntegration.mockResolvedValue({
      integrationId: 'int_1',
      provider: 'google',
      status: 'revoked',
    });

    const { POST } = await import('@/app/api/control-plane/integrations/[integrationId]/disconnect/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/control-plane/integrations/int_1/disconnect', {
      method: 'POST',
    });

    const response = await POST(request, { params: Promise.resolve({ integrationId: 'int_1' }) });
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(mockService.disconnectIntegration).toHaveBeenCalledWith('acct_1', {
      integrationId: 'int_1',
    });
  });
});
