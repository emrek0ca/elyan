import { NextRequest } from 'next/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getControlPlaneSessionToken: vi.fn(),
  isControlPlaneSessionConfigured: vi.fn(),
  executeInteractionStream: vi.fn(),
}));

vi.mock('@/core/control-plane/session', () => ({
  getControlPlaneSessionToken: mocks.getControlPlaneSessionToken,
  isControlPlaneSessionConfigured: mocks.isControlPlaneSessionConfigured,
}));

vi.mock('@/core/control-plane', () => ({
  getControlPlaneSessionToken: mocks.getControlPlaneSessionToken,
  isControlPlaneSessionConfigured: mocks.isControlPlaneSessionConfigured,
}));

vi.mock('@/core/interaction/orchestrator', () => ({
  executeInteractionStream: mocks.executeInteractionStream,
  normalizeInteractionError: (error: unknown) => ({
    code: 'request_failed',
    message: error instanceof Error ? error.message : 'request failed',
    status: 500,
  }),
}));

describe('local chat route', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.resetModules();
  });

  it('hydrates hosted session when available so authenticated requests can learn', async () => {
    mocks.isControlPlaneSessionConfigured.mockReturnValue(true);
    mocks.getControlPlaneSessionToken.mockResolvedValue({
      sub: 'usr_1',
      email: 'ayla@example.com',
      accountId: 'acct_1',
      role: 'owner',
    });
    mocks.executeInteractionStream.mockResolvedValue(new Response('ok', { status: 200 }));

    const { POST } = await import('@/app/api/chat/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'hello' }],
      }),
      headers: {
        'content-type': 'application/json',
      },
    });

    const response = await POST(request);

    expect(response.status).toBe(200);
    expect(mocks.getControlPlaneSessionToken).toHaveBeenCalledWith(request);
    expect(mocks.executeInteractionStream).toHaveBeenCalledWith(
      expect.objectContaining({
        controlPlaneSession: expect.objectContaining({ accountId: 'acct_1' }),
        requireHostedSession: false,
        metadata: expect.objectContaining({
          learningMode: 'authenticated',
        }),
      })
    );
  });

  it('keeps anonymous chat available with learning explicitly disabled', async () => {
    mocks.isControlPlaneSessionConfigured.mockReturnValue(true);
    mocks.getControlPlaneSessionToken.mockResolvedValue(null);
    mocks.executeInteractionStream.mockResolvedValue(new Response('ok', { status: 200 }));

    const { POST } = await import('@/app/api/chat/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/chat', {
      method: 'POST',
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'hello' }],
      }),
      headers: {
        'content-type': 'application/json',
      },
    });

    const response = await POST(request);

    expect(response.status).toBe(200);
    expect(mocks.getControlPlaneSessionToken).toHaveBeenCalledWith(request);
    expect(mocks.executeInteractionStream).toHaveBeenCalledWith(
      expect.objectContaining({
        controlPlaneSession: null,
        requireHostedSession: false,
        metadata: expect.objectContaining({
          learningMode: 'anonymous_disabled',
        }),
      })
    );
  });

  it('keeps anonymous preview chat available with learning explicitly disabled', async () => {
    mocks.isControlPlaneSessionConfigured.mockReturnValue(true);
    mocks.getControlPlaneSessionToken.mockResolvedValue(null);
    mocks.executeInteractionStream.mockResolvedValue(new Response('ok', { status: 200 }));

    const { POST } = await import('@/app/api/preview/chat/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/preview/chat', {
      method: 'POST',
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'preview hello' }],
      }),
      headers: {
        'content-type': 'application/json',
      },
    });

    const response = await POST(request);

    expect(response.status).toBe(200);
    expect(mocks.getControlPlaneSessionToken).toHaveBeenCalledWith(request);
    expect(mocks.executeInteractionStream).toHaveBeenCalledWith(
      expect.objectContaining({
        controlPlaneSession: null,
        requireHostedSession: false,
        metadata: expect.objectContaining({
          learningMode: 'anonymous_disabled',
        }),
      })
    );
  });
});
