import { createHash } from 'crypto';
import { getControlPlanePlan } from './catalog';
import type {
  ControlPlaneAccount,
  ControlPlaneDevice,
  ControlPlanePlan,
  ControlPlaneSubscription,
} from './types';

export type ControlPlaneConnectionKind = 'channel' | 'device' | 'billing' | 'session';

export type ControlPlaneConnectionLifecycle =
  | 'active'
  | 'expiring'
  | 'rotate'
  | 'revoked'
  | 'expired'
  | 'stale'
  | 'missing'
  | 'invalid';

export type ControlPlaneConnectionHealth = 'configured' | 'stale' | 'missing' | 'invalid';

export type ControlPlaneConnectionRecord = {
  kind: ControlPlaneConnectionKind;
  id: string;
  title: string;
  state: ControlPlaneConnectionLifecycle;
  health: ControlPlaneConnectionHealth;
  source: 'local' | 'hosted';
  enabled: boolean;
  scope: string;
  fingerprint?: string;
  preview?: string;
  last4?: string;
  expiresAt?: string;
  revokedAt?: string;
  lastSeenAt?: string;
  metadata: Record<string, unknown>;
};

export type ControlPlaneConnectionRegistrySnapshot = {
  records: ControlPlaneConnectionRecord[];
  summary: {
    total: number;
    active: number;
    expiring: number;
    rotate: number;
    revoked: number;
    expired: number;
    stale: number;
    missing: number;
    invalid: number;
    channels: number;
    devices: number;
    billing: number;
    sessions: number;
  };
};

export type ControlPlaneAccountPolicySnapshot = {
  planId: ControlPlaneAccount['subscription']['planId'];
  planTitle: string;
  subscriptionStatus: ControlPlaneSubscription['status'];
  syncState: ControlPlaneSubscription['syncState'];
  operationalStatus: 'trialing' | 'active' | 'past_due' | 'suspended' | 'canceled' | 'billing_pending' | 'sync_failed';
  provider: ControlPlaneSubscription['provider'];
  providerStatus?: string;
  retryCount: number;
  nextRetryAt?: string;
  currentPeriodEndsAt: string;
  monthlyCreditsRemaining: string;
  monthlyCreditsGranted: string;
  dailyRequestLimit: number;
  dailyToolActionLimit: number;
  entitlementDiff: {
    hostedAccess: boolean;
    hostedUsageAccounting: boolean;
    managedCredits: boolean;
    cloudRouting: boolean;
    advancedRouting: boolean;
    teamGovernance: boolean;
    hostedImprovementSignals: boolean;
  };
  notes: string[];
};

function hashSecret(value: string) {
  return createHash('sha256').update(value).digest('hex').slice(0, 12);
}

function previewSecret(value: string) {
  const trimmed = value.trim();
  if (trimmed.length <= 8) {
    return `${trimmed.slice(0, 2)}••••${trimmed.slice(-2)}`;
  }

  return `${trimmed.slice(0, 4)}••••${trimmed.slice(-4)}`;
}

function last4(value: string) {
  const trimmed = value.trim();
  return trimmed.slice(-4);
}

function countStates(records: ControlPlaneConnectionRecord[]) {
  return records.reduce(
    (summary, record) => {
      summary.total += 1;
      summary[record.state] += 1;
      if (record.kind === 'channel') {
        summary.channels += 1;
      } else if (record.kind === 'device') {
        summary.devices += 1;
      } else if (record.kind === 'billing') {
        summary.billing += 1;
      } else {
        summary.sessions += 1;
      }
      return summary;
    },
    {
      total: 0,
      active: 0,
      expiring: 0,
      rotate: 0,
      revoked: 0,
      expired: 0,
      stale: 0,
      missing: 0,
      invalid: 0,
      channels: 0,
      devices: 0,
      billing: 0,
      sessions: 0,
    }
  );
}

function buildLifecycleFromSecrets(enabled: boolean, values: Array<string | undefined>, configuredLabel: string) {
  const present = values.filter((value): value is string => Boolean(value && value.trim().length > 0));

  if (!enabled && present.length === 0) {
    return {
      state: 'missing' as const,
      health: 'missing' as const,
      preview: undefined,
      fingerprint: undefined,
      last4: undefined,
      notes: [`${configuredLabel} is disabled.`],
    };
  }

  if (enabled && present.length === 0) {
    return {
      state: 'invalid' as const,
      health: 'invalid' as const,
      preview: undefined,
      fingerprint: undefined,
      last4: undefined,
      notes: [`${configuredLabel} is enabled but missing required secrets.`],
    };
  }

  const material = present.join('|');
  return {
    state: enabled ? ('active' as const) : ('stale' as const),
    health: enabled ? ('configured' as const) : ('stale' as const),
    preview: previewSecret(present[0] ?? material),
    fingerprint: hashSecret(material),
    last4: last4(present[present.length - 1] ?? material),
    notes: enabled
      ? [`${configuredLabel} is configured and ready.`]
      : [`${configuredLabel} still has secrets but the adapter is disabled.`],
  };
}

export function buildRuntimeConnectionRegistry(input: {
  telegram: {
    enabled: boolean;
    mode: string;
    webhookPath: string;
    botToken?: string;
  };
  whatsappCloud: {
    enabled: boolean;
    webhookPath: string;
    accessToken?: string;
    phoneNumberId?: string;
    verifyToken?: string;
    appSecret?: string;
  };
  imessage: {
    enabled: boolean;
    webhookPath: string;
    serverUrl?: string;
    guid?: string;
    replyUrl?: string;
    webhookSecret?: string;
  };
  controlPlane: {
    storage: 'file' | 'postgres';
    hostedReady: boolean;
    callbackUrl: string;
    apiBaseUrl: string;
    billingMode: 'sandbox' | 'production';
    authConfigured: boolean;
    billingConfigured: boolean;
  };
}): ControlPlaneConnectionRegistrySnapshot {
  const telegram = buildLifecycleFromSecrets(
    input.telegram.enabled,
    [input.telegram.botToken],
    'Telegram bot token'
  );
  const whatsappCloud = buildLifecycleFromSecrets(
    input.whatsappCloud.enabled,
    [
      input.whatsappCloud.accessToken,
      input.whatsappCloud.phoneNumberId,
      input.whatsappCloud.verifyToken,
      input.whatsappCloud.appSecret,
    ],
    'WhatsApp Cloud credentials'
  );
  const imessage = buildLifecycleFromSecrets(
    input.imessage.enabled,
    [input.imessage.serverUrl, input.imessage.guid, input.imessage.replyUrl, input.imessage.webhookSecret],
    'iMessage / BlueBubbles credentials'
  );
  const sessionState: ControlPlaneConnectionRecord = {
    kind: 'session',
    id: 'control-plane-session',
    title: 'Hosted session',
    state: input.controlPlane.authConfigured ? 'active' : 'missing',
    health: input.controlPlane.authConfigured ? 'configured' : 'missing',
    source: 'hosted',
    enabled: input.controlPlane.authConfigured,
    scope: 'Auth.js session and account binding',
    preview: input.controlPlane.authConfigured ? 'session-bound' : undefined,
    metadata: {
      storage: input.controlPlane.storage,
      hostedReady: input.controlPlane.hostedReady,
    },
  };
  const billingState: ControlPlaneConnectionRecord = {
    kind: 'billing',
    id: 'iyzico-billing',
    title: 'iyzico billing',
    state: input.controlPlane.billingConfigured ? 'active' : 'missing',
    health: input.controlPlane.billingConfigured ? 'configured' : 'missing',
    source: 'hosted',
    enabled: input.controlPlane.billingConfigured,
    scope: `${input.controlPlane.billingMode} billing`,
    preview: input.controlPlane.billingConfigured ? input.controlPlane.apiBaseUrl : undefined,
    metadata: {
      billingMode: input.controlPlane.billingMode,
      callbackUrl: input.controlPlane.callbackUrl,
    },
  };

  const records: ControlPlaneConnectionRecord[] = [
    {
      kind: 'channel',
      id: 'telegram',
      title: 'Telegram',
      state: telegram.state,
      health: telegram.health,
      source: 'local',
      enabled: input.telegram.enabled,
      scope: input.telegram.webhookPath,
      fingerprint: telegram.fingerprint,
      preview: telegram.preview,
      last4: telegram.last4,
      metadata: {
        mode: input.telegram.mode,
      },
    },
    {
      kind: 'channel',
      id: 'whatsapp_cloud',
      title: 'WhatsApp Cloud',
      state: whatsappCloud.state,
      health: whatsappCloud.health,
      source: 'local',
      enabled: input.whatsappCloud.enabled,
      scope: input.whatsappCloud.webhookPath,
      fingerprint: whatsappCloud.fingerprint,
      preview: whatsappCloud.preview,
      last4: whatsappCloud.last4,
      metadata: {},
    },
    {
      kind: 'channel',
      id: 'imessage_bluebubbles',
      title: 'iMessage / BlueBubbles',
      state: imessage.state,
      health: imessage.health,
      source: 'local',
      enabled: input.imessage.enabled,
      scope: input.imessage.webhookPath,
      fingerprint: imessage.fingerprint,
      preview: imessage.preview,
      last4: imessage.last4,
      metadata: {},
    },
    sessionState,
    billingState,
  ];

  return {
    records,
    summary: countStates(records),
  };
}

export function buildHostedConnectionRegistry(input: {
  account: ControlPlaneAccount;
  devices: ControlPlaneDevice[];
}): ControlPlaneConnectionRegistrySnapshot {
  const plan = getControlPlanePlan(input.account.subscription.planId);
  const billingRecord: ControlPlaneConnectionRecord = {
    kind: 'billing',
    id: 'subscription',
    title: 'Subscription',
    state:
      input.account.subscription.syncState === 'failed'
        ? 'invalid'
        : input.account.subscription.status === 'past_due'
          ? 'expiring'
          : input.account.subscription.status === 'suspended'
            ? 'revoked'
            : input.account.subscription.status === 'canceled'
              ? 'expired'
              : input.account.subscription.syncState === 'pending'
                ? 'stale'
                : 'active',
    health:
      input.account.subscription.syncState === 'failed'
        ? 'invalid'
        : input.account.subscription.syncState === 'pending'
          ? 'stale'
          : 'configured',
    source: 'hosted',
    enabled: input.account.entitlements.hostedAccess,
    scope: plan.title,
    fingerprint: hashSecret(`${input.account.accountId}:${input.account.subscription.planId}`),
    preview: plan.title,
    metadata: {
      provider: input.account.subscription.provider,
      syncState: input.account.subscription.syncState,
      creditsGrantedThisPeriod: input.account.subscription.creditsGrantedThisPeriod,
    },
  };

  const deviceRecords = input.devices.map<ControlPlaneConnectionRecord>((device) => ({
    kind: 'device',
    id: device.deviceId,
    title: device.deviceLabel,
    state:
      device.status === 'revoked'
        ? 'revoked'
        : device.status === 'expired'
          ? 'expired'
          : device.metadata && typeof device.metadata === 'object' && !Array.isArray(device.metadata)
            ? (device.metadata as Record<string, unknown>).rotationStatus === 'rotated'
              ? 'rotate'
              : 'active'
            : 'active',
    health:
      device.status === 'revoked'
        ? 'invalid'
        : device.status === 'expired'
          ? 'missing'
          : 'configured',
    source: 'hosted',
    enabled: device.status === 'active',
    scope: device.accountId,
    fingerprint: hashSecret(device.deviceToken),
    preview: `${device.deviceLabel}`,
    last4: last4(device.deviceToken),
    expiresAt: (() => {
      const metadata = device.metadata;
      if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
        return undefined;
      }

      const expiresAt = (metadata as Record<string, unknown>).expiresAt;
      return typeof expiresAt === 'string' ? expiresAt : undefined;
    })(),
    revokedAt: device.revokedAt,
    lastSeenAt: device.lastSeenAt,
    metadata: device.metadata,
  }));

  return {
    records: [billingRecord, ...deviceRecords],
    summary: countStates([billingRecord, ...deviceRecords]),
  };
}

export function buildAccountPolicySnapshot(account: ControlPlaneAccount, plan: ControlPlanePlan): ControlPlaneAccountPolicySnapshot {
  const operationalStatus: ControlPlaneAccountPolicySnapshot['operationalStatus'] =
    account.subscription.syncState === 'failed'
      ? 'sync_failed'
      : account.subscription.syncState === 'pending'
        ? 'billing_pending'
        : account.subscription.status;

  const notes: string[] = [];
  if (account.subscription.syncState === 'pending') {
    notes.push('Checkout is pending and hosted entitlements are not fully active yet.');
  } else if (account.subscription.syncState === 'failed') {
    notes.push('Subscription sync failed and should be retried before relying on hosted access.');
  }

  if (!account.entitlements.hostedAccess) {
    notes.push('Hosted access is not available on the current plan or billing state.');
  }

  return {
    planId: plan.id,
    planTitle: plan.title,
    subscriptionStatus: account.subscription.status,
    syncState: account.subscription.syncState,
    operationalStatus,
    provider: account.subscription.provider,
    providerStatus: account.subscription.providerStatus,
    retryCount: account.subscription.retryCount,
    nextRetryAt: account.subscription.nextRetryAt,
    currentPeriodEndsAt: account.subscription.currentPeriodEndsAt,
    monthlyCreditsRemaining: account.usageSnapshot.monthlyCreditsRemaining,
    monthlyCreditsGranted: account.subscription.creditsGrantedThisPeriod,
    dailyRequestLimit: account.usageSnapshot.dailyRequestsLimit,
    dailyToolActionLimit: account.usageSnapshot.dailyHostedToolActionCallsLimit,
    entitlementDiff: {
      hostedAccess: account.entitlements.hostedAccess,
      hostedUsageAccounting: account.entitlements.hostedUsageAccounting,
      managedCredits: account.entitlements.managedCredits,
      cloudRouting: account.entitlements.cloudRouting,
      advancedRouting: account.entitlements.advancedRouting,
      teamGovernance: account.entitlements.teamGovernance,
      hostedImprovementSignals: account.entitlements.hostedImprovementSignals,
    },
    notes,
  };
}
