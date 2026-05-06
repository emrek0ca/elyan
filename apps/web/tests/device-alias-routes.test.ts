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
  bootstrapDevice: vi.fn(),
  pushDevice: vi.fn(),
  startDeviceLink: vi.fn(),
  rotateDeviceToken: vi.fn(),
  unlinkDevice: vi.fn(),
};

vi.mock('@/core/control-plane', () => ({
  getControlPlaneService: vi.fn(() => mockService),
}));

vi.mock('@/core/control-plane/session', () => ({
  requireControlPlaneSession: vi.fn(async () => mockSession),
  assertControlPlaneAccountAccess: vi.fn(),
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe('device alias routes', () => {
  it('reuses the hosted link start handler from the control-plane surface', async () => {
    mockService.startDeviceLink.mockResolvedValue({
      link: {
        linkCode: 'link_1',
      },
    });

    const { POST } = await import('@/app/api/devices/link/start/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/devices/link/start', {
      method: 'POST',
      body: JSON.stringify({ deviceLabel: 'Desktop' }),
      headers: {
        'content-type': 'application/json',
      },
    });

    const response = await POST(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(mockService.startDeviceLink).toHaveBeenCalledWith('acct_1', 'usr_1', {
      deviceLabel: 'Desktop',
    });
  });

  it('reuses the device sync bootstrap and push handlers', async () => {
    mockService.bootstrapDevice.mockResolvedValue({ ok: true, device: { deviceId: 'dev_1' } });
    mockService.pushDevice.mockResolvedValue({ ok: true, device: { deviceId: 'dev_1' } });

    const { GET: bootstrap } = await import('@/app/api/devices/sync/bootstrap/route');
    const bootstrapResponse = await bootstrap(
      new NextRequest('http://127.0.0.1:3000/api/devices/sync/bootstrap', {
        method: 'GET',
        headers: {
          authorization: 'Bearer devtok_1',
        },
      })
    );
    const bootstrapPayload = await bootstrapResponse.json();

    expect(bootstrapResponse.status).toBe(200);
    expect(bootstrapPayload.ok).toBe(true);
    expect(mockService.bootstrapDevice).toHaveBeenCalledWith('devtok_1');

    const { POST: push } = await import('@/app/api/sync/push/route');
    const pushResponse = await push(
      new NextRequest('http://127.0.0.1:3000/api/sync/push', {
        method: 'POST',
        body: JSON.stringify({ patches: [] }),
        headers: {
          'content-type': 'application/json',
          authorization: 'Bearer devtok_1',
        },
      })
    );
    const pushPayload = await pushResponse.json();

    expect(pushResponse.status).toBe(200);
    expect(pushPayload.ok).toBe(true);
    expect(mockService.pushDevice).toHaveBeenCalledWith({
      deviceToken: 'devtok_1',
      metadata: {},
    });
  });
});
