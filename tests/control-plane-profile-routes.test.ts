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

const profile = {
  session: {
    userId: 'usr_1',
    email: 'ayla@example.com',
    name: 'Ayla',
    accountId: 'acct_1',
    ownerType: 'individual',
    role: 'owner',
    planId: 'cloud_assisted',
    accountStatus: 'active',
    subscriptionStatus: 'active',
    subscriptionSyncState: 'synced',
    hostedAccess: true,
    hostedUsageAccounting: true,
    balanceCredits: '100.00',
    deviceCount: 1,
    activeDeviceCount: 1,
  },
  user: {
    userId: 'usr_1',
    email: 'ayla@example.com',
    displayName: 'Ayla',
    ownerType: 'individual',
    role: 'owner',
    status: 'active',
  },
  account: {
    accountId: 'acct_1',
    displayName: 'Ayla',
    ownerType: 'individual',
    balanceCredits: '100.00',
    billingCustomerRef: 'cust_1',
    status: 'active',
    deviceSummary: {
      total: 1,
      pending: 0,
      active: 1,
      revoked: 0,
      expired: 0,
    },
    subscription: {
      planId: 'cloud_assisted',
      status: 'active',
      provider: 'iyzico',
      syncState: 'synced',
      providerStatus: 'active',
      retryCount: 0,
      currentPeriodStartedAt: '2026-04-23T10:00:00.000Z',
      currentPeriodEndsAt: '2026-05-23T10:00:00.000Z',
      creditsGrantedThisPeriod: '1000.00',
    },
    plan: {
      title: 'Cloud-Assisted',
      summary: 'Managed hosted access with included credits.',
      monthlyPriceTRY: '399.00',
      monthlyIncludedCredits: '1000.00',
      dailyLimits: {
        hostedRequestsPerDay: 250,
        hostedToolActionCallsPerDay: 600,
      },
    },
    processedWebhookEventCount: 1,
    usageTotals: {
      inference: '0.00',
      retrieval: '0.00',
      integrations: '0.00',
      evaluation: '0.00',
    },
    usageSnapshot: {
      dayKey: '2026-04-24',
      resetAt: '2026-04-25T00:00:00.000Z',
      dailyRequests: 0,
      dailyRequestsLimit: 250,
      remainingRequests: 250,
      dailyHostedToolActionCalls: 0,
      dailyHostedToolActionCallsLimit: 600,
      remainingHostedToolActionCalls: 600,
      monthlyCreditsRemaining: '100.00',
      monthlyCreditsBurned: '900.00',
      state: 'ok',
    },
    entitlements: {
      hostedAccess: true,
      hostedUsageAccounting: true,
      managedCredits: true,
      cloudRouting: true,
      advancedRouting: true,
      teamGovernance: false,
      hostedImprovementSignals: true,
    },
  },
};

const mockService = {
  getHostedProfile: vi.fn(),
  listLedger: vi.fn(),
  listNotifications: vi.fn(),
  listDevices: vi.fn(),
  health: vi.fn(),
};

vi.mock('@/core/control-plane', () => ({
  getControlPlaneService: vi.fn(() => mockService),
  readControlPlaneHealthSnapshot: vi.fn(async () => ({
    ok: true,
    storage: 'postgres',
    iyzicoConfigured: true,
    connection: {
      storage: 'postgres',
      hostedReady: true,
      callbackUrl: 'https://elyan.dev/api/control-plane/billing/iyzico/webhook',
      apiBaseUrl: 'https://api.iyzipay.com',
      billingMode: 'production',
    },
  })),
}));

vi.mock('@/core/control-plane/auth', () => ({
  isHostedAuthConfigured: vi.fn(() => true),
}));

vi.mock('@/core/control-plane/session', () => ({
  requireControlPlaneSession: vi.fn(async () => mockSession),
  assertControlPlaneAccountAccess: vi.fn(),
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe('control-plane canonical profile routes', () => {
  it('returns the same canonical profile from auth/me', async () => {
    mockService.getHostedProfile.mockResolvedValue(profile);

    const { GET } = await import('@/app/api/control-plane/auth/me/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/control-plane/auth/me', { method: 'GET' });

    const response = await GET(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(payload.session.subscriptionSyncState).toBe('synced');
    expect(payload.profile.session.hostedAccess).toBe(true);
    expect(payload.account.deviceSummary.total).toBe(1);
    expect(payload.account.interactionState).toBeUndefined();
    expect(mockService.getHostedProfile).toHaveBeenCalledWith('acct_1');
  });

  it('returns the same canonical profile from the panel route', async () => {
    mockService.getHostedProfile.mockResolvedValue(profile);
    mockService.listDevices.mockResolvedValue([
      {
        deviceId: 'dev_1',
        deviceLabel: 'MacBook Pro',
        status: 'active',
        deviceToken: 'secret-token',
        metadata: { internal: true },
        linkedAt: '2026-04-23T10:00:00.000Z',
        lastSeenAt: '2026-04-24T10:00:00.000Z',
        lastSeenReleaseTag: 'v1.1.0',
        createdAt: '2026-04-23T10:00:00.000Z',
        updatedAt: '2026-04-24T10:00:00.000Z',
      },
    ]);

    const { GET } = await import('@/app/api/control-plane/panel/route');
    const request = new NextRequest('http://127.0.0.1:3000/api/control-plane/panel', { method: 'GET' });

    const response = await GET(request);
    const payload = await response.json();

    expect(response.status).toBe(200);
    expect(payload.ok).toBe(true);
    expect(payload.profile.session.subscriptionStatus).toBe('active');
    expect(payload.account.subscription.syncState).toBe('synced');
    expect(payload.account.deviceSummary.total).toBe(1);
    expect(payload.devices[0].deviceToken).toBeUndefined();
    expect(payload.ledger).toBeUndefined();
    expect(payload.notifications).toBeUndefined();
    expect(payload.health).toBeUndefined();
    expect(mockService.getHostedProfile).toHaveBeenCalledWith('acct_1');
  });
});
