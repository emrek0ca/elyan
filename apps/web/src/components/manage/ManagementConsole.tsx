'use client';

import React from 'react';
import { motion } from 'framer-motion';
import Link from 'next/link';
import {
  ArrowUpRight,
  RefreshCw,
  Sparkles,
} from 'lucide-react';
import { shouldFetchHostedControlPlane } from '@/core/control-plane/hosted-fetch';
import type { CapabilityDirectorySnapshot } from '@/core/capabilities/directory';
import type { OptimizationStatusSnapshot } from '@/core/optimization/status';
import type { RuntimeSettings } from '@/core/runtime-settings';
import type { OperatorApproval, OperatorRun } from '@/core/operator/runs';
import type { RuntimeRegistrySnapshot } from '@/core/runtime-registry';

type DashboardStatus = {
  ok: boolean;
  runtime: 'local-first';
  surfaces: {
    local: { key: 'local'; label: string; ready: boolean; summary: string; detail: string };
    shared: { key: 'shared'; label: string; ready: boolean; summary: string; detail: string };
    hosted: { key: 'hosted'; label: string; ready: boolean; summary: string; detail: string };
  };
  readiness: {
    hasLocalModels: boolean;
    searchEnabled: boolean;
    searchAvailable: boolean;
    mcpConfigured: boolean;
    voiceConfigured: boolean;
    workspaceConfigured: boolean;
  };
  models: Array<{ id: string; name: string; provider: string; type: string }>;
  capabilities: CapabilityDirectorySnapshot;
  connections: {
    records: Array<{
      kind: 'channel' | 'device' | 'billing' | 'session';
      id: string;
      title: string;
      state: string;
      health: string;
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
    }>;
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
  channels: {
    telegram: { configured: boolean; enabled: boolean; mode: string; webhookPath: string; costProfile?: string; probe?: { ok: boolean; status: string | number } | null };
    whatsappCloud: { configured: boolean; enabled: boolean; webhookPath: string; costProfile?: string; probe?: { ok: boolean; status: string | number } | null };
    whatsappBaileys: { configured: boolean; enabled: boolean; sessionPath: string; costProfile?: string; supportLevel?: string; probe?: { ok: boolean; status: string | number } | null };
    imessage: { configured: boolean; enabled: boolean; webhookPath: string; costProfile?: string; probe?: { ok: boolean; status: string | number } | null };
  };
  localAgent: {
    enabled: boolean;
    allowedRoots: string[];
    protectedPathCount: number;
    evidenceDir: string;
    approvalPolicy: RuntimeSettings['localAgent']['approvalPolicy'];
  };
  team: {
    settings: RuntimeSettings['team'];
    status: {
      configured: boolean;
      recentRuns: Array<{
        runId: string;
        status: 'completed' | 'failed';
        finishedAt: string;
        query: string;
        mode: 'speed' | 'research';
        modelId: string;
        modelProvider: string;
        taskCount: number;
        agentCount: number;
        verifier: {
          passed: boolean;
          summary: string;
        };
      }>;
      summary: {
        recentRunCount: number;
        latestStatus: string;
        latestRunId?: string;
        latestVerifierPassed?: boolean;
      };
    };
  };
  mcp: {
    configured: boolean;
    servers: RuntimeSettings['mcp']['servers'];
  };
  controlPlane: {
    health?: {
      ok?: boolean;
      storage?: string;
      syncSummary?: {
        subscriptions: {
          total: number;
          trialing: number;
          active: number;
          past_due: number;
          suspended: number;
          canceled: number;
          unbound: number;
          pending: number;
          synced: number;
          failed: number;
          ready: number;
          billingPending: number;
          syncFailed: number;
        };
        devices: {
          total: number;
          pending: number;
          active: number;
          revoked: number;
          expired: number;
        };
      };
      evaluationSummary?: {
        windowCount: number;
        averageLatencyMs: number;
        retrievalCoverageRate: number;
        toolCompletionRate: number;
        latestSignal?: {
          signalId: string;
          createdAt: string;
          mode: string;
          taskIntent: string;
          routingMode: string;
          quality: 'good' | 'mixed' | 'poor' | 'skipped';
          modelId: string;
          modelProvider: string;
          sourceCount: number;
          citationCount: number;
          toolCallCount: number;
          latencyMs: number;
          answerLength: number;
        };
        qualityCounts: Record<'good' | 'mixed' | 'poor' | 'skipped', number>;
        promotionCandidates: number;
      };
      connection?: {
        storage?: string;
        hostedReady?: boolean;
        callbackUrl?: string;
        apiBaseUrl?: string;
        billingMode?: 'sandbox' | 'production';
      };
      database?: {
        storage: 'file' | 'postgres';
        mode: 'file_backed' | 'postgres';
        configured: boolean;
        ready: boolean;
        detail: string;
        totalCount?: number;
        idleCount?: number;
        waitingCount?: number;
        maxCount?: number;
      };
    };
  };
  operator: {
    status: 'healthy' | 'degraded' | 'unknown';
    runs: {
      total: number;
      blocked: number;
      completed: number;
      failed: number;
      byMode: Record<OperatorRun['mode'], number>;
      latest?: {
        id: string;
        title: string;
        mode: OperatorRun['mode'];
        status: OperatorRun['status'];
        updatedAt: string;
        reasoningDepth: OperatorRun['reasoning']['depth'];
        approvalCount: number;
        pendingApprovals: number;
      };
    };
    approvals: {
      total: number;
      pending: number;
      approved: number;
      rejected: number;
      expired: number;
      latest?: {
        id: string;
        title: string;
        status: OperatorApproval['status'];
        approvalLevel: OperatorApproval['approvalLevel'];
        riskLevel: OperatorApproval['riskLevel'];
        requestedAt: string;
      };
    };
    summary: string;
  };
  registry: RuntimeRegistrySnapshot;
  optimization: OptimizationStatusSnapshot;
  workspace: {
    ready: boolean;
    summary: {
      configuredSourceCount: number;
      connectedSourceCount: number;
      availableSourceCount: number;
      jobCount: number;
      activeJobCount: number;
      briefItemCount: number;
    };
    sources: Array<{
      kind: 'gmail' | 'calendar' | 'notion' | 'github' | 'obsidian' | 'mcp';
      title: string;
      state: 'connected' | 'available' | 'partial' | 'unconfigured' | 'offline';
      origin: 'direct' | 'mcp' | 'local' | 'derived';
      summary: string;
      detail: string;
      stats?: {
        serverCount?: number;
        toolCount?: number;
        resourceCount?: number;
        promptCount?: number;
        noteCount?: number;
        issueCount?: number;
        pullRequestCount?: number;
      };
      lastSyncAt?: string;
    }>;
    jobs: Array<{
      id: string;
      title: string;
      cadence: string;
      enabled: boolean;
      summary: string;
      nextRunAt?: string;
    }>;
    brief: Array<{
      kind: 'note' | 'repo' | 'surface';
      title: string;
      detail: string;
      source: string;
      timestamp?: string;
    }>;
    nextSteps: string[];
  };
  runtimeSettings: RuntimeSettings;
  nextSteps: string[];
};

type RuntimeConfigPayload = {
  settings?: Record<string, unknown>;
  secrets?: Record<string, string | null>;
};

type HostedPanelPayload = {
  ok: boolean;
  session?: {
    email?: string;
    role?: string;
    accountId?: string;
    planId?: string;
    subscriptionStatus?: string;
    subscriptionSyncState?: string;
    hostedAccess?: boolean;
    hostedUsageAccounting?: boolean;
  };
  profile?: {
    session: {
      userId: string;
      email: string;
      name: string;
      accountId: string;
      ownerType: string;
      role: string;
      planId: string;
      accountStatus: string;
      subscriptionStatus: string;
      subscriptionSyncState: string;
      hostedAccess: boolean;
      hostedUsageAccounting: boolean;
      balanceCredits: string;
      deviceCount: number;
      activeDeviceCount: number;
    };
    user?: {
      userId: string;
      email: string;
      displayName: string;
      ownerType: string;
      role: string;
      status: string;
    };
    account: {
      accountId: string;
      displayName: string;
      ownerType?: string;
      balanceCredits?: string;
      status: string;
      subscription: {
        planId: string;
        status: string;
        provider: string;
        syncState: string;
        providerStatus?: string;
        retryCount: number;
        nextRetryAt?: string;
        currentPeriodEndsAt: string;
        currentPeriodStartedAt: string;
        creditsGrantedThisPeriod: string;
        lastSyncError?: string;
      };
      plan?: {
        title: string;
        monthlyPriceTRY: string;
        monthlyIncludedCredits: string;
      };
      deviceSummary?: {
        total: number;
        pending: number;
        active: number;
        revoked: number;
        expired: number;
      };
      usageSnapshot: {
        monthlyCreditsRemaining: string;
        monthlyCreditsBurned: string;
        dailyRequests: number;
        dailyRequestsLimit: number;
        remainingRequests: number;
        dailyHostedToolActionCalls: number;
        dailyHostedToolActionCallsLimit: number;
        remainingHostedToolActionCalls: number;
        state: string;
        resetAt: string;
      };
      processedWebhookEventCount?: number;
    };
  };
  account?: {
    displayName: string;
    accountId: string;
    ownerType?: string;
    balanceCredits?: string;
    status: string;
    subscription: {
      status: string;
      syncState: string;
      provider: string;
      providerStatus?: string;
      retryCount: number;
      nextRetryAt?: string;
      currentPeriodEndsAt: string;
      currentPeriodStartedAt: string;
      creditsGrantedThisPeriod: string;
      lastSyncError?: string;
    };
    plan?: {
      title: string;
      monthlyPriceTRY: string;
      monthlyIncludedCredits: string;
    };
    integrationSummary?: {
      total: number;
      connected: number;
      needsAttention: number;
    };
    entitlements?: {
      hostedAccess: boolean;
    };
    integrations?: Record<
      string,
      {
        integrationId: string;
        provider: 'google' | 'github' | 'notion';
        displayName: string;
        status: string;
        scopes: string[];
        surfaces: string[];
        externalAccountLabel?: string;
        lastSyncedAt?: string;
        lastError?: string;
        createdAt: string;
        updatedAt: string;
      }
    >;
    deviceSummary?: {
      total: number;
      pending: number;
      active: number;
      revoked: number;
      expired: number;
    };
    usageSnapshot: {
      monthlyCreditsRemaining: string;
      monthlyCreditsBurned: string;
      dailyRequests: number;
      dailyRequestsLimit: number;
      remainingRequests: number;
      dailyHostedToolActionCalls: number;
      dailyHostedToolActionCallsLimit: number;
      remainingHostedToolActionCalls: number;
      state: string;
      resetAt: string;
    };
    processedWebhookEventCount?: number;
  };
  devices?: Array<{
    deviceId: string;
    deviceLabel: string;
    status: string;
    linkedAt: string;
    lastSeenAt?: string;
    lastSeenReleaseTag?: string;
    revokedAt?: string;
  }>;
};

type IntegrationCatalogPayload = {
  ok: boolean;
  providers?: Array<{
    provider: 'google' | 'github' | 'notion';
    displayName: string;
    configured: boolean;
    surfaces: Array<'gmail' | 'calendar' | 'github' | 'notion'>;
    defaultScopes: string[];
  }>;
  integrations?: Array<{
    integrationId: string;
    provider: 'google' | 'github' | 'notion';
    displayName: string;
    status: string;
    scopes: string[];
    surfaces: string[];
    externalAccountLabel?: string;
    lastSyncedAt?: string;
    lastError?: string;
    createdAt: string;
    updatedAt: string;
  }>;
};

const INTEGRATION_PROVIDER_FALLBACKS: Record<
  'google' | 'github' | 'notion',
  {
    displayName: string;
    surfaces: Array<'gmail' | 'calendar' | 'github' | 'notion'>;
  }
> = {
  google: {
    displayName: 'Google Workspace',
    surfaces: ['gmail', 'calendar'],
  },
  github: {
    displayName: 'GitHub',
    surfaces: ['github'],
  },
  notion: {
    displayName: 'Notion',
    surfaces: ['notion'],
  },
};

type RuntimeForm = {
  preferredModelId: string;
  routingMode: 'local_only' | 'local_first' | 'balanced' | 'cloud_preferred';
  searchEnabled: boolean;
};

type ChannelKey = 'telegram' | 'whatsappCloud' | 'whatsappBaileys' | 'imessage';

type ChannelForm = {
  telegram: {
    enabled: boolean;
    mode: 'polling' | 'webhook';
    webhookPath: string;
    botUsername: string;
    botToken: string;
    webhookSecret: string;
    allowedChatIds: string;
  };
  whatsappCloud: {
    enabled: boolean;
    webhookPath: string;
    phoneNumberId: string;
    accessToken: string;
    verifyToken: string;
    appSecret: string;
  };
  whatsappBaileys: {
    enabled: boolean;
    sessionPath: string;
  };
  imessage: {
    enabled: boolean;
    webhookPath: string;
    serverUrl: string;
    guid: string;
    webhookSecret: string;
  };
};

async function fetchStatus(): Promise<DashboardStatus> {
  const response = await fetch('/api/dashboard/status', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to load dashboard status (${response.status})`);
  }

  return response.json();
}

async function patchRuntimeConfig(payload: RuntimeConfigPayload) {
  const response = await fetch('/api/runtime/config', {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error || `Failed to save runtime config (${response.status})`);
  }

  return response.json() as Promise<{ ok: boolean }>;
}

async function fetchPanel(): Promise<HostedPanelPayload | null> {
  const response = await fetch('/api/control-plane/panel', {
    credentials: 'include',
    cache: 'no-store',
  });

  if (!response.ok) {
    return null;
  }

  return response.json();
}

async function fetchIntegrations(): Promise<IntegrationCatalogPayload | null> {
  const response = await fetch('/api/control-plane/integrations', {
    credentials: 'include',
    cache: 'no-store',
  });

  if (!response.ok) {
    return null;
  }

  return response.json();
}

function hydrateChannelForm(status: DashboardStatus): ChannelForm {
  return {
    telegram: {
      enabled: status.runtimeSettings.channels.telegram.enabled,
      mode: status.runtimeSettings.channels.telegram.mode,
      webhookPath: status.runtimeSettings.channels.telegram.webhookPath,
      botUsername: status.runtimeSettings.channels.telegram.botUsername ?? '',
      botToken: '',
      webhookSecret: status.runtimeSettings.channels.telegram.webhookSecret ?? '',
      allowedChatIds: (status.runtimeSettings.channels.telegram.allowedChatIds ?? []).join(', '),
    },
    whatsappCloud: {
      enabled: status.runtimeSettings.channels.whatsappCloud.enabled,
      webhookPath: status.runtimeSettings.channels.whatsappCloud.webhookPath,
      phoneNumberId: status.runtimeSettings.channels.whatsappCloud.phoneNumberId ?? '',
      accessToken: '',
      verifyToken: status.runtimeSettings.channels.whatsappCloud.verifyToken ?? '',
      appSecret: status.runtimeSettings.channels.whatsappCloud.appSecret ?? '',
    },
    whatsappBaileys: {
      enabled: status.runtimeSettings.channels.whatsappBaileys.enabled,
      sessionPath: status.runtimeSettings.channels.whatsappBaileys.sessionPath,
    },
    imessage: {
      enabled: status.runtimeSettings.channels.imessage.enabled,
      webhookPath: status.runtimeSettings.channels.imessage.webhookPath,
      serverUrl: status.runtimeSettings.channels.imessage.serverUrl ?? '',
      guid: status.runtimeSettings.channels.imessage.guid ?? '',
      webhookSecret: status.runtimeSettings.channels.imessage.webhookSecret ?? '',
    },
  };
}

function createInitialChannelForm(): ChannelForm {
  return {
    telegram: {
      enabled: false,
      mode: 'polling',
      webhookPath: '/api/channels/telegram/webhook',
      botUsername: '',
      botToken: '',
      webhookSecret: '',
      allowedChatIds: '',
    },
    whatsappCloud: {
      enabled: false,
      webhookPath: '/api/channels/whatsapp/webhook',
      phoneNumberId: '',
      accessToken: '',
      verifyToken: '',
      appSecret: '',
    },
    whatsappBaileys: {
      enabled: false,
      sessionPath: 'storage/channels/whatsapp-baileys.json',
    },
    imessage: {
      enabled: false,
      webhookPath: '/api/channels/imessage/bluebubbles/webhook',
      serverUrl: '',
      guid: '',
      webhookSecret: '',
    },
  };
}

export function ManagementConsole() {
  const [status, setStatus] = React.useState<DashboardStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [panelInfo, setPanelInfo] = React.useState<HostedPanelPayload | null>(null);
  const [integrationCatalog, setIntegrationCatalog] = React.useState<IntegrationCatalogPayload | null>(null);
  const [runtimeForm, setRuntimeForm] = React.useState<RuntimeForm>({
    preferredModelId: '',
    routingMode: 'local_first',
    searchEnabled: true,
  });
  const [channelForm, setChannelForm] = React.useState<ChannelForm>(createInitialChannelForm);
  const [selectedChannel, setSelectedChannel] = React.useState<ChannelKey>('telegram');
  const [mcpJson, setMcpJson] = React.useState('[]');

  const syncFromStatus = React.useCallback((next: DashboardStatus) => {
    setStatus(next);
    setRuntimeForm({
      preferredModelId: next.runtimeSettings.routing.preferredModelId ?? '',
      routingMode: next.runtimeSettings.routing.routingMode,
      searchEnabled: next.runtimeSettings.routing.searchEnabled,
    });
    setChannelForm(hydrateChannelForm(next));
    if (next.runtimeSettings.channels.whatsappCloud.enabled) {
      setSelectedChannel('whatsappCloud');
    } else if (next.runtimeSettings.channels.whatsappBaileys.enabled) {
      setSelectedChannel('whatsappBaileys');
    } else if (next.runtimeSettings.channels.imessage.enabled) {
      setSelectedChannel('imessage');
    } else {
      setSelectedChannel('telegram');
    }
    setMcpJson(JSON.stringify(next.runtimeSettings.mcp.servers, null, 2));
  }, []);

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        const next = await fetchStatus();
        const [nextPanel, nextIntegrations] = shouldFetchHostedControlPlane(next)
          ? await Promise.all([
              fetchPanel().catch(() => null),
              fetchIntegrations().catch(() => null),
            ])
          : [null, null];

        if (cancelled) {
          return;
        }

        syncFromStatus(next);
        setPanelInfo(nextPanel);
        setIntegrationCatalog(nextIntegrations);
      } catch (loadError) {
        if (cancelled) {
          return;
        }

        setError(loadError instanceof Error ? loadError.message : 'Failed to load dashboard');
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [syncFromStatus]);

  const refresh = React.useCallback(async () => {
    const next = await fetchStatus();
    const [nextPanel, nextIntegrations] = shouldFetchHostedControlPlane(next)
      ? await Promise.all([
          fetchPanel().catch(() => null),
          fetchIntegrations().catch(() => null),
        ])
      : [null, null];

    syncFromStatus(next);
    setPanelInfo(nextPanel);
    setIntegrationCatalog(nextIntegrations);
  }, [syncFromStatus]);

  const handleConnectIntegration = React.useCallback((provider: 'google' | 'github' | 'notion') => {
    window.location.assign(`/api/control-plane/integrations/${provider}/connect?returnTo=/manage#manage-integrations`);
  }, []);

  const integrationProviders = (['google', 'github', 'notion'] as const).map((provider) => {
    const catalogEntry = integrationCatalog?.providers?.find((entry) => entry.provider === provider);
    return {
      provider,
      displayName: catalogEntry?.displayName ?? INTEGRATION_PROVIDER_FALLBACKS[provider].displayName,
      configured: catalogEntry?.configured ?? false,
      surfaces: catalogEntry?.surfaces ?? INTEGRATION_PROVIDER_FALLBACKS[provider].surfaces,
      defaultScopes: catalogEntry?.defaultScopes ?? [],
    };
  });

  const channelOptions: Array<{ key: ChannelKey; label: string }> = [
    { key: 'telegram', label: 'Telegram' },
    { key: 'whatsappCloud', label: 'WhatsApp Cloud' },
    { key: 'whatsappBaileys', label: 'WhatsApp Bridge' },
    { key: 'imessage', label: 'iMessage' },
  ];

  const connectedIntegrations = Object.values(panelInfo?.account?.integrations ?? {});
  const mlAvailability = status?.registry.ml.live ? 'live' : status?.registry.ml.cached ? 'cached' : 'offline';
  const runtimeOperator = status?.operator ?? {
    status: 'unknown' as const,
    runs: {
      total: 0,
      blocked: 0,
      completed: 0,
      failed: 0,
      byMode: { auto: 0, research: 0, code: 0, cowork: 0 },
      latest: undefined,
    },
    approvals: {
      total: 0,
      pending: 0,
      approved: 0,
      rejected: 0,
      expired: 0,
      latest: undefined,
    },
    summary: 'Operator data is unavailable.',
  };
  const runtimeSurfaces = status?.surfaces ?? {
    local: {
      key: 'local' as const,
      label: 'Local runtime',
      ready: false,
      summary: 'Local runtime data is unavailable.',
      detail: 'The runtime snapshot is still loading or could not be read.',
    },
    shared: {
      key: 'shared' as const,
      label: 'Shared control plane',
      ready: false,
      summary: 'Shared control plane data is unavailable.',
      detail: 'The runtime snapshot is still loading or could not be read.',
    },
    hosted: {
      key: 'hosted' as const,
      label: 'Hosted surface',
      ready: false,
      summary: 'Hosted surface data is unavailable.',
      detail: 'The runtime snapshot is still loading or could not be read.',
    },
  };
  const runtimeConnections = status?.connections ?? {
    records: [],
    summary: {
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
    },
  };

  const handleRuntimeSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      await patchRuntimeConfig({
        settings: {
          routing: {
            preferredModelId: runtimeForm.preferredModelId.trim() || undefined,
            routingMode: runtimeForm.routingMode,
            searchEnabled: runtimeForm.searchEnabled,
          },
        },
      });
      syncFromStatus(await fetchStatus());
      setNotice('Runtime settings saved.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save runtime settings');
    } finally {
      setSaving(false);
    }
  };

  const handleChannelSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const telegramChatIds = channelForm.telegram.allowedChatIds
        .split(',')
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
      const secrets: Record<string, string> = {};

      if (channelForm.telegram.botToken.trim()) {
        secrets.TELEGRAM_BOT_TOKEN = channelForm.telegram.botToken.trim();
      }
      if (channelForm.telegram.webhookSecret.trim()) {
        secrets.TELEGRAM_WEBHOOK_SECRET = channelForm.telegram.webhookSecret.trim();
      }
      if (channelForm.whatsappCloud.phoneNumberId.trim()) {
        secrets.WHATSAPP_CLOUD_PHONE_NUMBER_ID = channelForm.whatsappCloud.phoneNumberId.trim();
      }
      if (channelForm.whatsappCloud.accessToken.trim()) {
        secrets.WHATSAPP_CLOUD_ACCESS_TOKEN = channelForm.whatsappCloud.accessToken.trim();
      }
      if (channelForm.whatsappCloud.verifyToken.trim()) {
        secrets.WHATSAPP_CLOUD_VERIFY_TOKEN = channelForm.whatsappCloud.verifyToken.trim();
      }
      if (channelForm.whatsappCloud.appSecret.trim()) {
        secrets.WHATSAPP_CLOUD_APP_SECRET = channelForm.whatsappCloud.appSecret.trim();
      }
      if (channelForm.imessage.serverUrl.trim()) {
        secrets.BLUEBUBBLES_SERVER_URL = channelForm.imessage.serverUrl.trim();
      }
      if (channelForm.imessage.guid.trim()) {
        secrets.BLUEBUBBLES_SERVER_GUID = channelForm.imessage.guid.trim();
      }
      if (channelForm.imessage.webhookSecret.trim()) {
        secrets.BLUEBUBBLES_WEBHOOK_SECRET = channelForm.imessage.webhookSecret.trim();
      }

      await patchRuntimeConfig({
        settings: {
          channels: {
            telegram: {
              ...channelForm.telegram,
              botUsername: channelForm.telegram.botUsername.trim() || undefined,
              allowedChatIds: telegramChatIds,
            },
            whatsappCloud: channelForm.whatsappCloud,
            whatsappBaileys: channelForm.whatsappBaileys,
            imessage: channelForm.imessage,
          },
        },
        secrets,
      });
      syncFromStatus(await fetchStatus());
      setNotice('Channel settings saved.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save channel settings');
    } finally {
      setSaving(false);
    }
  };

  const handleMcpSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const servers = JSON.parse(mcpJson);
      if (!Array.isArray(servers)) {
        throw new Error('MCP config must be a JSON array.');
      }

      await patchRuntimeConfig({
        settings: {
          mcp: {
            servers,
          },
        },
      });
      syncFromStatus(await fetchStatus());
      setNotice('MCP servers saved.');
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Failed to save MCP config');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="manage-page__loading">Loading local runtime status…</div>;
  }

  if (!status) {
    return <div className="manage-page__loading">{error ?? 'Dashboard unavailable.'}</div>;
  }

  return (
    <div className="manage-page manage-page--focus">
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
        className="manage-focus"
      >
        <header className="manage-focus__hero">
          <div>
            <div className="manage-page__eyebrow">
              <Sparkles size={12} strokeWidth={2.2} />
              Manage
            </div>
            <h1 className="manage-focus__title">Elyan</h1>
            <p className="manage-focus__lede">Local-first control. Route, run, and connect from one calm surface.</p>
          </div>
          <div className="manage-focus__actions">
            <button type="button" className="manage-page__button manage-page__button--ghost" onClick={() => void refresh()}>
              <RefreshCw size={14} strokeWidth={2.2} />
              Refresh
            </button>
            <Link className="manage-page__button" href="/chat/new">
              <ArrowUpRight size={14} strokeWidth={2.2} />
              Chat
            </Link>
          </div>
        </header>

        <section className="manage-focus__status" aria-label="Runtime status">
          <StatusChip label="Local" value={runtimeSurfaces.local.ready ? 'Ready' : 'Off'} tone={runtimeSurfaces.local.ready ? 'success' : 'warning'} />
          <StatusChip label="ML" value={status.registry.ml.latest?.title ?? mlAvailability} tone={status.registry.ml.live ? 'success' : 'warning'} />
          <StatusChip label="Approvals" value={String(status.registry.summary.pendingApprovalCount)} tone={status.registry.summary.pendingApprovalCount ? 'warning' : 'neutral'} />
          <StatusChip label="MCP" value={status.registry.mcp.enabled ? 'On' : 'Off'} tone={status.registry.mcp.enabled ? 'accent' : 'neutral'} />
        </section>

        <section className="manage-action-grid" aria-label="Primary actions">
          <article className="manage-action-card manage-action-card--wide">
            <div className="manage-action-card__top">
              <div>
                <div className="manage-action-card__label">Runtime</div>
                <h2>Route work</h2>
              </div>
              <StatusChip label="Mode" value={runtimeForm.routingMode} tone="neutral" />
            </div>
            <div className="manage-compact-form">
              <label className="manage-field">
                <span>Model</span>
                <input
                  value={runtimeForm.preferredModelId}
                  onChange={(event) => setRuntimeForm((current) => ({ ...current, preferredModelId: event.target.value }))}
                  placeholder={status.registry.ml.latest?.id ?? 'ollama:llama3.2'}
                />
              </label>
              <label className="manage-field">
                <span>Routing</span>
                <select
                  value={runtimeForm.routingMode}
                  onChange={(event) =>
                    setRuntimeForm((current) => ({
                      ...current,
                      routingMode: event.target.value as RuntimeForm['routingMode'],
                    }))
                  }
                >
                  <option value="local_only">local_only</option>
                  <option value="local_first">local_first</option>
                  <option value="balanced">balanced</option>
                  <option value="cloud_preferred">cloud_preferred</option>
                </select>
              </label>
              <label className="manage-toggle">
                <input
                  type="checkbox"
                  checked={runtimeForm.searchEnabled}
                  onChange={(event) => setRuntimeForm((current) => ({ ...current, searchEnabled: event.target.checked }))}
                />
                <span>Search</span>
              </label>
            </div>
            <div className="manage-action-card__actions">
              <button type="button" className="manage-page__button" onClick={() => void handleRuntimeSave()} disabled={saving}>
                Save
              </button>
            </div>
          </article>

          <article className="manage-action-card">
            <div className="manage-action-card__label">Operator</div>
            <h2>{runtimeOperator.status}</h2>
            <div className="manage-mini-stats">
              <Metric label="Runs" value={String(runtimeOperator.runs.total)} />
              <Metric label="Pending" value={String(runtimeOperator.approvals.pending)} />
            </div>
            <div className="manage-action-card__actions">
              <Link className="manage-page__button manage-page__button--ghost" href="/chat/new">New run</Link>
            </div>
          </article>

          <article className="manage-action-card">
            <div className="manage-action-card__label">Workspace</div>
            <h2>{status.workspace.summary.connectedSourceCount} connected</h2>
            <div className="manage-mini-stats">
              <Metric label="Jobs" value={String(status.workspace.summary.jobCount)} />
              <Metric label="Active" value={String(status.workspace.summary.activeJobCount)} />
            </div>
            <div className="manage-action-card__actions">
              <button type="button" className="manage-page__button manage-page__button--ghost" onClick={() => void refresh()}>
                Refresh
              </button>
            </div>
          </article>

          <article className="manage-action-card">
            <div className="manage-action-card__label">Models</div>
            <h2>{status.registry.ml.counts.total} available</h2>
            <div className="manage-mini-stats">
              <Metric label="Local" value={String(status.registry.ml.counts.local)} />
              <Metric label="Cloud" value={String(status.registry.ml.counts.cloud)} />
            </div>
            <div className="manage-action-card__actions">
              <Link className="manage-page__button manage-page__button--ghost" href="/chat/new">Use</Link>
            </div>
          </article>

          <article className="manage-action-card">
            <div className="manage-action-card__label">Channels</div>
            <h2>{runtimeConnections.summary.active} active</h2>
            <div className="manage-app-row">
              {channelOptions.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  className="manage-app-pill"
                  style={
                    selectedChannel === option.key
                      ? {
                          borderColor: 'rgba(56, 92, 255, 0.3)',
                          background: 'rgba(56, 92, 255, 0.08)',
                          color: 'var(--text-0)',
                        }
                      : undefined
                  }
                  onClick={() => setSelectedChannel(option.key)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="manage-form manage-form--compact">
              <label className="manage-toggle manage-field--inline" style={{ gridColumn: '1 / -1' }}>
                <input
                  type="checkbox"
                  checked={channelForm[selectedChannel].enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      [selectedChannel]: {
                        ...current[selectedChannel],
                        enabled: event.target.checked,
                      },
                    }))
                  }
                />
                <span>Enabled</span>
              </label>

              {selectedChannel === 'telegram' ? (
                <>
                  <label className="manage-field">
                    <span>Bot token</span>
                    <input
                      value={channelForm.telegram.botToken}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          telegram: {
                            ...current.telegram,
                            botToken: event.target.value,
                          },
                        }))
                      }
                      placeholder="TELEGRAM_BOT_TOKEN"
                    />
                  </label>
                  <label className="manage-field">
                    <span>Username</span>
                    <input
                      value={channelForm.telegram.botUsername}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          telegram: {
                            ...current.telegram,
                            botUsername: event.target.value,
                          },
                        }))
                      }
                      placeholder="@botname"
                    />
                  </label>
                  <label className="manage-field">
                    <span>Webhook secret</span>
                    <input
                      value={channelForm.telegram.webhookSecret}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          telegram: {
                            ...current.telegram,
                            webhookSecret: event.target.value,
                          },
                        }))
                      }
                      placeholder="secret"
                    />
                  </label>
                  <label className="manage-field">
                    <span>Chat IDs</span>
                    <input
                      value={channelForm.telegram.allowedChatIds}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          telegram: {
                            ...current.telegram,
                            allowedChatIds: event.target.value,
                          },
                        }))
                      }
                      placeholder="123, 456"
                    />
                  </label>
                </>
              ) : null}

              {selectedChannel === 'whatsappCloud' ? (
                <>
                  <label className="manage-field">
                    <span>Phone number ID</span>
                    <input
                      value={channelForm.whatsappCloud.phoneNumberId}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          whatsappCloud: {
                            ...current.whatsappCloud,
                            phoneNumberId: event.target.value,
                          },
                        }))
                      }
                      placeholder="PHONE_NUMBER_ID"
                    />
                  </label>
                  <label className="manage-field">
                    <span>Access token</span>
                    <input
                      value={channelForm.whatsappCloud.accessToken}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          whatsappCloud: {
                            ...current.whatsappCloud,
                            accessToken: event.target.value,
                          },
                        }))
                      }
                      placeholder="WHATSAPP_CLOUD_ACCESS_TOKEN"
                    />
                  </label>
                  <label className="manage-field">
                    <span>Verify token</span>
                    <input
                      value={channelForm.whatsappCloud.verifyToken}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          whatsappCloud: {
                            ...current.whatsappCloud,
                            verifyToken: event.target.value,
                          },
                        }))
                      }
                      placeholder="verify token"
                    />
                  </label>
                  <label className="manage-field">
                    <span>App secret</span>
                    <input
                      value={channelForm.whatsappCloud.appSecret}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          whatsappCloud: {
                            ...current.whatsappCloud,
                            appSecret: event.target.value,
                          },
                        }))
                      }
                      placeholder="WHATSAPP_CLOUD_APP_SECRET"
                    />
                  </label>
                </>
              ) : null}

              {selectedChannel === 'whatsappBaileys' ? (
                <>
                  <label className="manage-field">
                    <span>Session path</span>
                    <input
                      value={channelForm.whatsappBaileys.sessionPath}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          whatsappBaileys: {
                            ...current.whatsappBaileys,
                            sessionPath: event.target.value,
                          },
                        }))
                      }
                      placeholder="storage/channels/whatsapp-baileys.json"
                    />
                  </label>
                  <div className="manage-page__help" style={{ gridColumn: '1 / -1' }}>
                    Pairing is done from the CLI.
                  </div>
                </>
              ) : null}

              {selectedChannel === 'imessage' ? (
                <>
                  <label className="manage-field">
                    <span>Server URL</span>
                    <input
                      value={channelForm.imessage.serverUrl}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          imessage: {
                            ...current.imessage,
                            serverUrl: event.target.value,
                          },
                        }))
                      }
                      placeholder="https://..."
                    />
                  </label>
                  <label className="manage-field">
                    <span>GUID</span>
                    <input
                      value={channelForm.imessage.guid}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          imessage: {
                            ...current.imessage,
                            guid: event.target.value,
                          },
                        }))
                      }
                      placeholder="BLUEBUBBLES_SERVER_GUID"
                    />
                  </label>
                  <label className="manage-field">
                    <span>Webhook secret</span>
                    <input
                      value={channelForm.imessage.webhookSecret}
                      onChange={(event) =>
                        setChannelForm((current) => ({
                          ...current,
                          imessage: {
                            ...current.imessage,
                            webhookSecret: event.target.value,
                          },
                        }))
                      }
                      placeholder="secret"
                    />
                  </label>
                </>
              ) : null}
            </div>
            <div className="manage-action-card__actions">
              <button type="button" className="manage-page__button" onClick={() => void handleChannelSave()} disabled={saving}>
                Save
              </button>
            </div>
          </article>

          <article className="manage-action-card">
            <div className="manage-action-card__label">MCP</div>
            <h2>{status.registry.mcp.enabled ? 'Enabled' : 'Off'}</h2>
            <textarea
              className="manage-textarea manage-textarea--compact"
              rows={4}
              value={mcpJson}
              onChange={(event) => setMcpJson(event.target.value)}
              aria-label="MCP servers"
            />
            <div className="manage-action-card__actions">
              <button type="button" className="manage-page__button" onClick={() => void handleMcpSave()} disabled={saving}>
                Save
              </button>
            </div>
          </article>

          <article className="manage-action-card">
            <div className="manage-action-card__label">Apps</div>
            <h2>{connectedIntegrations.length} linked</h2>
            <div className="manage-app-row">
              {integrationProviders.map((provider) => (
                <button
                  key={provider.provider}
                  type="button"
                  className="manage-app-pill"
                  onClick={() => handleConnectIntegration(provider.provider)}
                  disabled={saving || !provider.configured}
                >
                  {provider.displayName}
                </button>
              ))}
            </div>
            <div className="manage-action-card__actions">
              <button type="button" className="manage-page__button manage-page__button--ghost" onClick={() => void refresh()}>
                Check
              </button>
            </div>
          </article>
        </section>

        {notice ? <div className="manage-banner manage-banner--success">{notice}</div> : null}
        {error ? <div className="manage-banner manage-banner--error">{error}</div> : null}
      </motion.div>
    </div>
  );

}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="manage-metric">
      <div className="manage-metric__label">{label}</div>
      <div className="manage-metric__value">{value}</div>
    </div>
  );
}

function StatusChip({ label, value, tone }: { label: string; value: string; tone: 'neutral' | 'accent' | 'success' | 'warning' }) {
  return (
    <div className={`manage-chip manage-chip--${tone}`}>
      <span className="manage-chip__label">{label}</span>
      <span className="manage-chip__value">{value}</span>
    </div>
  );
}
