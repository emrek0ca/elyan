'use client';

import React from 'react';
import { motion } from 'framer-motion';
import Link from 'next/link';
import {
  AlertTriangle,
  ArrowUpRight,
  BadgeCheck,
  Cpu,
  Database,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { ControlPlaneStateBadge } from '@/components/control-plane/ControlPlaneStateBadge';
import type { CapabilityDirectorySnapshot } from '@/core/capabilities';
import {
  formatCapabilityApproval,
  formatCapabilityRisk,
} from '@/core/capabilities/profiles';
import {
  buildControlPlaneAnchorId,
} from '@/core/control-plane/display';
import type { OptimizationStatusSnapshot } from '@/core/optimization/status';
import type { RuntimeSettings } from '@/core/runtime-settings';
import type { OperatorApproval, OperatorRun } from '@/core/operator/runs';

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

type ReleasePayload = {
  currentVersion: string;
  currentTagName: string;
  repository: string;
  publishable: boolean;
  updateAvailable: boolean;
  updateStatus: 'current' | 'update_available' | 'unavailable';
  updateMessage: string;
  latest: {
    tagName: string;
    publishedAt: string;
    htmlUrl: string;
    complete: boolean;
  } | null;
  requiredAssets: string[];
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

type OperatorRunsPayload = {
  ok: boolean;
  runs: OperatorRun[];
};

type OperatorApprovalsPayload = {
  ok: boolean;
  approvals: OperatorApproval[];
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

type ChannelForm = ReturnType<typeof createInitialChannelForm>;

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

async function fetchRelease(): Promise<ReleasePayload> {
  const response = await fetch('/api/releases/latest', { cache: 'no-store' });

  if (!response.ok) {
    throw new Error(`Failed to load release stream (${response.status})`);
  }

  const payload = (await response.json()) as ReleasePayload & { ok?: boolean };
  return payload;
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

async function fetchOperatorRuns(): Promise<OperatorRunsPayload> {
  const response = await fetch('/api/runs', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to load operator runs (${response.status})`);
  }

  return response.json();
}

async function fetchOperatorApprovals(): Promise<OperatorApprovalsPayload> {
  const response = await fetch('/api/approvals', { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Failed to load operator approvals (${response.status})`);
  }

  return response.json();
}

function hydrateChannelForm(status: DashboardStatus) {
  return {
    telegram: {
      enabled: status.runtimeSettings.channels.telegram.enabled,
      mode: status.runtimeSettings.channels.telegram.mode,
      webhookPath: status.runtimeSettings.channels.telegram.webhookPath,
      botUsername: status.runtimeSettings.channels.telegram.botUsername ?? '',
    },
    whatsappCloud: {
      enabled: status.runtimeSettings.channels.whatsappCloud.enabled,
      webhookPath: status.runtimeSettings.channels.whatsappCloud.webhookPath,
    },
    whatsappBaileys: {
      enabled: status.runtimeSettings.channels.whatsappBaileys.enabled,
      sessionPath: status.runtimeSettings.channels.whatsappBaileys.sessionPath,
    },
    imessage: {
      enabled: status.runtimeSettings.channels.imessage.enabled,
      webhookPath: status.runtimeSettings.channels.imessage.webhookPath,
    },
  };
}

function createInitialChannelForm() {
  return {
    telegram: {
      enabled: false,
      mode: 'polling',
      webhookPath: '/api/channels/telegram/webhook',
      botUsername: '',
    },
    whatsappCloud: {
      enabled: false,
      webhookPath: '/api/channels/whatsapp/webhook',
    },
    whatsappBaileys: {
      enabled: false,
      sessionPath: 'storage/channels/whatsapp-baileys.json',
    },
    imessage: {
      enabled: false,
      webhookPath: '/api/channels/imessage/bluebubbles/webhook',
    },
  };
}

export function ManagementConsole() {
  const [status, setStatus] = React.useState<DashboardStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [releaseInfo, setReleaseInfo] = React.useState<ReleasePayload | null>(null);
  const [panelInfo, setPanelInfo] = React.useState<HostedPanelPayload | null>(null);
  const [integrationCatalog, setIntegrationCatalog] = React.useState<IntegrationCatalogPayload | null>(null);
  const [operatorRuns, setOperatorRuns] = React.useState<OperatorRun[]>([]);
  const [operatorApprovals, setOperatorApprovals] = React.useState<OperatorApproval[]>([]);
  const [runtimeForm, setRuntimeForm] = React.useState<RuntimeForm>({
    preferredModelId: '',
    routingMode: 'local_first',
    searchEnabled: true,
  });
  const [channelForm, setChannelForm] = React.useState<ChannelForm>(createInitialChannelForm);
  const [mcpJson, setMcpJson] = React.useState('[]');

  const syncFromStatus = React.useCallback((next: DashboardStatus) => {
    setStatus(next);
    setRuntimeForm({
      preferredModelId: next.runtimeSettings.routing.preferredModelId ?? '',
      routingMode: next.runtimeSettings.routing.routingMode,
      searchEnabled: next.runtimeSettings.routing.searchEnabled,
    });
    setChannelForm(hydrateChannelForm(next));
    setMcpJson(JSON.stringify(next.runtimeSettings.mcp.servers, null, 2));
  }, []);

  React.useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        const [next, nextRelease, nextPanel, nextRuns, nextApprovals] = await Promise.all([
          fetchStatus(),
          fetchRelease().catch(() => null),
          fetchPanel().catch(() => null),
          fetchOperatorRuns().catch(() => ({ ok: true, runs: [] })),
          fetchOperatorApprovals().catch(() => ({ ok: true, approvals: [] })),
        ]);
        const nextIntegrations = await fetchIntegrations().catch(() => null);

        if (cancelled) {
          return;
        }

        syncFromStatus(next);
        setReleaseInfo(nextRelease);
        setPanelInfo(nextPanel);
        setIntegrationCatalog(nextIntegrations);
        setOperatorRuns(nextRuns.runs);
        setOperatorApprovals(nextApprovals.approvals);
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
    const [next, nextRelease, nextPanel, nextRuns, nextApprovals] = await Promise.all([
      fetchStatus(),
      fetchRelease().catch(() => null),
      fetchPanel().catch(() => null),
      fetchOperatorRuns().catch(() => ({ ok: true, runs: [] })),
      fetchOperatorApprovals().catch(() => ({ ok: true, approvals: [] })),
    ]);
    const nextIntegrations = await fetchIntegrations().catch(() => null);

    syncFromStatus(next);
    setReleaseInfo(nextRelease);
    setPanelInfo(nextPanel);
    setIntegrationCatalog(nextIntegrations);
    setOperatorRuns(nextRuns.runs);
    setOperatorApprovals(nextApprovals.approvals);
  }, [syncFromStatus]);

  const handleConnectIntegration = React.useCallback((provider: 'google' | 'github' | 'notion') => {
    window.location.assign(`/api/control-plane/integrations/${provider}/connect?returnTo=/manage#manage-integrations`);
  }, []);

  const handleDisconnectIntegration = async (integrationId: string) => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const response = await fetch(`/api/control-plane/integrations/${integrationId}/disconnect`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.error || `Failed to disconnect integration (${response.status})`);
      }

      await refresh();
      setNotice('Integration disconnected.');
    } catch (disconnectError) {
      setError(disconnectError instanceof Error ? disconnectError.message : 'Failed to disconnect integration');
    } finally {
      setSaving(false);
    }
  };

  const handleTestIntegration = async (provider: 'google' | 'github' | 'notion') => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const action =
        provider === 'google'
          ? { provider, action: 'gmail.listMessages', parameters: { maxResults: 3 } }
          : provider === 'github'
            ? { provider, action: 'user.profile', parameters: {} }
            : { provider, action: 'search', parameters: { query: 'Inbox', pageSize: 5 } };

      const response = await fetch('/api/control-plane/integrations/actions', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(action),
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.error || `Failed to run integration action (${response.status})`);
      }

      await refresh();
      setNotice(`${provider} test action completed.`);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : 'Failed to run integration action');
    } finally {
      setSaving(false);
    }
  };

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

  const connectedIntegrations = Object.values(panelInfo?.account?.integrations ?? {});
  const hostedSession = panelInfo?.profile?.session;
  const hostedProfileUser = panelInfo?.profile?.user;

  const handleRuntimeSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      await patchRuntimeConfig({
        settings: {
          routing: {
            preferredModelId: runtimeForm.preferredModelId.trim() || null,
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
      await patchRuntimeConfig({
        settings: {
          channels: {
            telegram: {
              ...channelForm.telegram,
              botUsername: channelForm.telegram.botUsername.trim() || null,
            },
            whatsappCloud: channelForm.whatsappCloud,
            whatsappBaileys: channelForm.whatsappBaileys,
            imessage: channelForm.imessage,
          },
        },
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

  const activeCapabilities = status?.capabilities.capabilities.filter((entry) => entry.enabled) ?? [];
  const disabledCapabilities = status?.capabilities.capabilities.filter((entry) => !entry.enabled) ?? [];
  const pendingOperatorApprovals = operatorApprovals.filter((approval) => approval.status === 'pending');

  if (loading) {
    return <div className="manage-page__loading">Loading local runtime status…</div>;
  }

  if (!status) {
    return <div className="manage-page__loading">{error ?? 'Dashboard unavailable.'}</div>;
  }

  return (
    <div className="manage-page">
      <motion.div
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="manage-page__stack"
      >
        <header className="manage-hero">
          <div className="manage-hero__copy">
            <div className="manage-page__eyebrow">
              <Sparkles size={12} strokeWidth={2.2} />
              Command center
            </div>
            <h1 className="manage-page__title">Local-first runtime. Visible policy. Explicit integrations.</h1>
            <p className="manage-page__lead">
              Inspect readiness, capabilities, skills, and optional hosted surfaces from one place. Every connected surface stays visible before it becomes useful.
            </p>
            <div className="manage-hero__chips">
              <StatusChip label="Runtime" value={status.runtime} tone="neutral" />
              <StatusChip label="Enabled capabilities" value={String(activeCapabilities.length)} tone="accent" />
              <StatusChip label="Approval AUTO" value={String(status.capabilities.summary.autoApprovalCapabilityCount)} tone="success" />
              <StatusChip label="Approval SCREEN" value={String(status.capabilities.summary.screenApprovalCapabilityCount)} tone="warning" />
              <StatusChip label="MCP servers" value={String(status.capabilities.summary.mcpServerCount)} tone="neutral" />
              <StatusChip label="Connections" value={String(status.connections.summary.total)} tone="neutral" />
              <StatusChip label="Workspace" value={String(status.workspace.summary.connectedSourceCount)} tone="accent" />
              <StatusChip label="Team mode" value={status.team.settings.enabled ? status.team.settings.defaultMode : 'off'} tone={status.team.settings.enabled ? 'accent' : 'neutral'} />
              <StatusChip label="Local operator" value={status.localAgent.enabled ? 'on' : 'off'} tone={status.localAgent.enabled ? 'warning' : 'neutral'} />
              <StatusChip label="Optimization" value={status.optimization.ready ? 'ready' : 'partial'} tone={status.optimization.ready ? 'success' : 'warning'} />
            </div>
          </div>
          <div className="manage-hero__actions">
            <button type="button" className="manage-page__button manage-page__button--ghost" onClick={() => void refresh()}>
              <RefreshCw size={14} strokeWidth={2.2} />
              Refresh
            </button>
          <Link className="manage-page__button manage-page__button--ghost" href="/chat/new">
            <ArrowUpRight size={14} strokeWidth={2.2} />
            Open chat
          </Link>
          </div>
        </header>

        <section className="manage-grid manage-grid--surfaces">
          <StatSurfaceCard
            title="Local runtime"
            icon={<Cpu size={16} strokeWidth={2.1} />}
            ready={status.surfaces.local.ready}
            summary={status.surfaces.local.summary}
            detail={status.surfaces.local.detail}
          />
          <StatSurfaceCard
            title="Shared control plane"
            icon={<Database size={16} strokeWidth={2.1} />}
            ready={status.surfaces.shared.ready}
            summary={status.surfaces.shared.summary}
            detail={status.surfaces.shared.detail}
          />
          <StatSurfaceCard
            title="Hosted surface"
            icon={<ShieldCheck size={16} strokeWidth={2.1} />}
            ready={status.surfaces.hosted.ready}
            summary={status.surfaces.hosted.summary}
            detail={status.surfaces.hosted.detail}
          />
        </section>

        <section className="manage-grid manage-grid--main">
          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Local operator</div>
              <div className="manage-card__hint">Permissioned computer control</div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="State" value={status.localAgent.enabled ? 'enabled' : 'disabled'} />
              <Metric label="Roots" value={String(status.localAgent.allowedRoots.length)} />
              <Metric label="Protected" value={String(status.localAgent.protectedPathCount)} />
              <Metric label="Writes" value={status.localAgent.approvalPolicy.writeSafe} />
            </div>
            <div className="manage-list manage-list--dense" style={{ marginTop: '0.85rem' }}>
              {status.localAgent.allowedRoots.slice(0, 4).map((root) => (
                <SurfaceRow key={root} label={root} value="allowed" hint={`Evidence: ${status.localAgent.evidenceDir}`} />
              ))}
              {status.localAgent.allowedRoots.length === 0 && (
                <div className="manage-page__help">Grant a workspace root from the CLI before local filesystem or terminal actions run.</div>
              )}
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Workspace surfaces</div>
              <div className="manage-card__hint">
                {status.workspace.summary.connectedSourceCount} connected · {status.workspace.summary.configuredSourceCount} configured
              </div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="Available" value={String(status.workspace.summary.availableSourceCount)} />
              <Metric label="Jobs" value={String(status.workspace.summary.jobCount)} />
              <Metric label="Active jobs" value={String(status.workspace.summary.activeJobCount)} />
              <Metric label="Brief items" value={String(status.workspace.summary.briefItemCount)} />
            </div>
            <div className="manage-list manage-list--dense">
              {status.workspace.sources.slice(0, 6).map((source) => (
                <SurfaceRow
                  key={source.kind}
                  label={source.title}
                  value={source.state.replace('_', ' ')}
                  hint={`${source.summary} · ${source.origin}`}
                />
              ))}
            </div>
            <div className="manage-card__title-row" style={{ marginTop: '0.85rem' }}>
              <div className="manage-card__title">Automation jobs</div>
              <div className="manage-card__hint">Recurring workspace maintenance</div>
            </div>
            <div className="manage-list manage-list--dense">
              {status.workspace.jobs.slice(0, 5).map((job) => (
                <SurfaceRow
                  key={job.id}
                  label={job.title}
                  value={job.enabled ? 'enabled' : 'idle'}
                  hint={`${job.cadence}${job.nextRunAt ? ` · next ${new Date(job.nextRunAt).toLocaleString()}` : ''} · ${job.summary}`}
                />
              ))}
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Team runtime</div>
              <div className="manage-card__hint">Typed local-first multi-agent runs</div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="Mode" value={status.team.settings.enabled ? status.team.settings.defaultMode : 'off'} />
              <Metric label="Agents" value={String(status.team.settings.maxConcurrentAgents)} />
              <Metric label="Task limit" value={String(status.team.settings.maxTasksPerRun)} />
              <Metric label="Cloud escalation" value={status.team.settings.allowCloudEscalation ? 'on' : 'off'} />
            </div>
            <div className="manage-list manage-list--dense" style={{ marginTop: '0.85rem' }}>
              {status.team.status.recentRuns.length > 0 ? (
                status.team.status.recentRuns.slice(0, 4).map((run) => (
                  <SurfaceRow
                    key={run.runId}
                    label={run.query}
                    value={run.verifier.passed ? 'verified' : run.status}
                    hint={`${run.taskCount} tasks · ${run.agentCount} agents · ${run.modelProvider}:${run.modelId} · ${new Date(run.finishedAt).toLocaleString()}`}
                  />
                ))
              ) : (
                <div className="manage-page__help">
                  Team mode is ready. Complex research, coding, and multi-step work will create auditable local runs here.
                </div>
              )}
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Optimization lane</div>
              <div className="manage-card__hint">Hybrid classical and quantum-inspired</div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="Ready" value={status.optimization.ready ? 'yes' : 'partial'} />
              <Metric label="Capability" value={status.optimization.capabilityReady ? 'enabled' : 'disabled'} />
              <Metric label="Bridge" value={status.optimization.bridgeToolReady ? 'enabled' : 'disabled'} />
              <Metric label="Skill" value={status.optimization.skillReady ? 'enabled' : 'disabled'} />
            </div>
            <div className="manage-list manage-list--dense" style={{ marginTop: '0.85rem' }}>
              <SurfaceRow
                label="Summary"
                value={status.optimization.capabilityId}
                hint={status.optimization.summary}
              />
              <SurfaceRow
                label="Demo modes"
                value={status.optimization.demoModes.join(' · ')}
                hint={status.optimization.guidance[0]}
              />
              <SurfaceRow
                label="Guardrails"
                value="local-first"
                hint={status.optimization.guidance[1]}
              />
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Operator runs</div>
              <div className="manage-card__hint">v1.3 plan, approval, and artifact trail</div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="Runs" value={String(operatorRuns.length)} />
              <Metric label="Pending approvals" value={String(pendingOperatorApprovals.length)} />
              <Metric label="Blocked" value={String(operatorRuns.filter((run) => run.status === 'blocked').length)} />
              <Metric label="Deep runs" value={String(operatorRuns.filter((run) => run.reasoning.depth === 'deep').length)} />
              <Metric label="Failed gates" value={String(operatorRuns.reduce((total, run) => total + run.qualityGates.filter((gate) => gate.status === 'failed').length, 0))} />
            </div>
            <div className="manage-list manage-list--dense" style={{ marginTop: '0.85rem' }}>
              {operatorRuns.length > 0 ? (
                operatorRuns.slice(0, 5).map((run) => (
                  <SurfaceRow
                    key={run.id}
                    label={run.title}
                    value={`${run.mode} · ${run.status}`}
                    hint={`${run.reasoning.depth}/${run.reasoning.maxPasses} passes · ${run.qualityGates.filter((gate) => gate.status === 'passed').length}/${run.qualityGates.length} gates · ${run.continuity.openItemCount} open · ${run.continuity.nextSteps[0]?.title ?? run.continuity.summary} · ${new Date(run.updatedAt).toLocaleString()}`}
                  />
                ))
              ) : (
                <div className="manage-page__help">
                  Create one with <code>elyan run --mode research &quot;...&quot;</code> or start a chat task to capture an operator trail.
                </div>
              )}
            </div>
            {pendingOperatorApprovals.length > 0 && (
              <div className="manage-list manage-list--dense" style={{ marginTop: '0.85rem' }}>
                {pendingOperatorApprovals.slice(0, 3).map((approval) => (
                  <SurfaceRow
                    key={approval.id}
                    label={approval.title}
                    value={`${approval.approvalLevel}/${approval.riskLevel}`}
                    hint={`Use CLI approval ${approval.id}; requested ${new Date(approval.requestedAt).toLocaleString()}`}
                  />
                ))}
              </div>
            )}
          </article>
        </section>

        <section className="manage-grid manage-grid--main">
          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Workspace brief</div>
              <div className="manage-card__hint">Daily context and recent signals</div>
            </div>
            <div className="manage-list manage-list--dense">
              {status.workspace.brief.length > 0 ? (
                status.workspace.brief.slice(0, 5).map((item) => (
                  <SurfaceRow
                    key={`${item.source}:${item.title}`}
                    label={item.title}
                    value={item.kind}
                    hint={`${item.source} · ${item.detail}`}
                  />
                ))
              ) : (
                <div className="manage-page__help">
                  Connect a workspace source to surface notes, repository context, and an operator-ready brief.
                </div>
              )}
            </div>
            <div className="manage-note-grid" style={{ marginTop: '0.85rem' }}>
              {status.workspace.nextSteps.slice(0, 3).map((step, index) => (
                <div key={step} className="manage-note">
                  <div className="manage-list__primary">Step {index + 1}</div>
                  <div className="manage-list__secondary">{step}</div>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="manage-grid manage-grid--main">
          <article className="manage-card manage-card--wide" id="manage-capability-directory" tabIndex={-1}>
            <div className="manage-card__title-row">
              <div className="manage-card__title">Capability directory</div>
              <div className="manage-card__hint">{status.capabilities.summary.enabledLocalCapabilityCount} of {status.capabilities.summary.localCapabilityCount} enabled</div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="Domains" value={String(status.capabilities.summary.categoryCount)} />
              <Metric label="Libraries" value={String(status.capabilities.summary.libraryCount)} />
              <Metric label="Safe by default" value={String(status.capabilities.summary.safeByDefaultCapabilityCount)} />
              <Metric label="High risk" value={String(status.capabilities.summary.highRiskCapabilityCount)} />
              <Metric label="Disabled" value={String(disabledCapabilities.length)} />
            </div>
            <div className="manage-domain__chips" style={{ marginTop: '0.8rem' }}>
              {status.capabilities.filters.sources.map((source) => (
                <span key={source} className="manage-domain__chip">
                  {source.replace('_', ' ')}
                </span>
              ))}
            </div>
            <div className="manage-domain__chips" style={{ marginTop: '0.45rem' }}>
              {status.capabilities.filters.libraries.slice(0, 8).map((library) => (
                <span key={library} className="manage-domain__chip">
                  {library}
                </span>
              ))}
            </div>
            <div className="manage-domain-grid">
              {status.capabilities.domains.map((domain) => (
                <DomainCard key={domain.category} domain={domain} />
              ))}
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Approval map</div>
              <div className="manage-card__hint">Risk-aware default gates</div>
            </div>
            <div className="manage-list manage-list--dense">
              {status.capabilities.approvalMatrix.map((item) => (
                <div key={item.level} className="manage-list__row manage-list__row--compact">
                  <div>
                    <div className="manage-list__primary">{formatCapabilityApproval(item.level)}</div>
                    <div className="manage-list__secondary">{item.summary}</div>
                  </div>
                  <div className="manage-list__stack">
                    <div className="manage-list__badge">{item.capabilityCount}</div>
                    <div className="manage-list__small">{item.enabledCapabilityCount} enabled</div>
                  </div>
                </div>
              ))}
            </div>
          </article>
        </section>

        <section className="manage-grid manage-grid--main">
          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Skills</div>
              <div className="manage-card__hint">{status.capabilities.summary.enabledSkillCount} enabled built-ins</div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="Built-in" value={String(status.capabilities.summary.skillCount)} />
              <Metric label="Installed" value={String(status.capabilities.summary.installedSkillCount)} />
              <Metric label="Techniques" value={String(status.capabilities.skills.summary.agenticTechniqueCount)} />
              <Metric label="Local-only" value={String(status.capabilities.skills.summary.localOnlySkillCount)} />
              <Metric label="Hostable" value={String(status.capabilities.skills.summary.hostedAllowedSkillCount)} />
              <Metric label="MCP configured" value={String(status.capabilities.skills.summary.mcpConfiguredServerCount)} />
              <Metric label="MCP disabled" value={String(status.capabilities.skills.summary.mcpDisabledServerCount)} />
              <Metric label="Disabled tools" value={String(status.capabilities.skills.summary.mcpDisabledToolCount)} />
            </div>
            <div className="manage-page__help">
              {status.capabilities.skills.summary.mcpConfigurationStatus === 'ready'
                ? `${status.capabilities.skills.summary.mcpEnabledServerCount} MCP server(s) enabled for policy-bound skills.`
                : status.capabilities.skills.summary.mcpConfigurationStatus === 'unavailable'
                  ? status.capabilities.skills.summary.mcpConfigurationError ?? 'MCP configuration could not be loaded.'
                  : 'MCP-aware skills stay available, but no MCP servers are configured yet.'}
            </div>
            <div className="manage-list manage-list--dense">
              {status.capabilities.skills.builtIn.slice(0, 6).map((skill) => (
                <div key={skill.id} className="manage-list__row manage-list__row--compact">
                  <div>
                    <div className="manage-list__primary">{skill.title}</div>
                    <div className="manage-list__secondary">{skill.description}</div>
                  </div>
                  <div className="manage-list__stack">
                    <div className="manage-list__badge">{skill.enabled ? 'enabled' : 'disabled'}</div>
                    <div className="manage-list__small">{skill.riskLevel} · {skill.approvalLevel}</div>
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">MCP</div>
              <div className="manage-card__hint">{status.capabilities.summary.mcpConfiguredServerCount} configured</div>
            </div>
            <div className="manage-metrics manage-metrics--dense">
              <Metric label="Reachable" value={String(status.capabilities.summary.mcpReachableServerCount)} />
              <Metric label="Blocked" value={String(status.capabilities.summary.mcpBlockedServerCount)} />
              <Metric label="Disabled" value={String(status.capabilities.summary.mcpDisabledServerCount)} />
              <Metric label="Tools" value={String(status.capabilities.summary.mcpToolCount)} />
            </div>
            <div className="manage-list manage-list--dense">
              {status.capabilities.mcp.mcpServers.length > 0 ? (
                status.capabilities.mcp.mcpServers.slice(0, 4).map((server) => (
                  <SurfaceRow
                    key={server.id}
                    label={server.id}
                    value={(server.state ?? (server.enabled ? 'configured' : 'disabled')).replace('_', ' ')}
                    hint={server.stateReason ?? server.endpoint ?? 'No live state recorded yet.'}
                  />
                ))
              ) : (
                <div className="manage-page__help">
                  {status.mcp.configured
                    ? status.capabilities.mcp.discovery.cached
                      ? `Live MCP surfaces are unavailable right now. Showing the last known good snapshot from ${status.capabilities.mcp.discovery.lastHealthyAt ?? 'a prior run'}.`
                      : 'Live MCP surfaces are unavailable right now.'
                    : 'Optional. Add stdio or streamable-http servers only when you actively use them.'}
                </div>
              )}
            </div>
          </article>
        </section>

        <section className="manage-grid manage-grid--main">
          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Runtime routing</div>
              <div className="manage-card__hint">Model and retrieval policy</div>
            </div>
            <div className="manage-form">
              <label className="manage-field">
                <span>Preferred model</span>
                <input
                  value={runtimeForm.preferredModelId}
                  onChange={(event) => setRuntimeForm((current) => ({ ...current, preferredModelId: event.target.value }))}
                  placeholder="ollama:llama3.2"
                />
              </label>
              <label className="manage-field">
                <span>Routing mode</span>
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
              <label className="manage-field manage-field--inline">
                <input
                  type="checkbox"
                  checked={runtimeForm.searchEnabled}
                  onChange={(event) => setRuntimeForm((current) => ({ ...current, searchEnabled: event.target.checked }))}
                />
                <span>Enable web search when SearXNG is available</span>
              </label>
              <div className="manage-form__actions">
                <button type="button" className="manage-page__button" onClick={() => void handleRuntimeSave()} disabled={saving}>
                  Save runtime settings
                </button>
              </div>
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Channel integrations</div>
              <div className="manage-card__hint">Optional adapters only</div>
            </div>
            <div className="manage-form">
              <label className="manage-field manage-field--inline">
                <input
                  type="checkbox"
                  checked={channelForm.telegram.enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      telegram: { ...current.telegram, enabled: event.target.checked },
                    }))
                  }
                />
                <span>Telegram</span>
              </label>
              <label className="manage-field">
                <span>Telegram mode</span>
                <select
                  value={channelForm.telegram.mode}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      telegram: { ...current.telegram, mode: event.target.value },
                    }))
                  }
                >
                  <option value="polling">polling</option>
                  <option value="webhook">webhook</option>
                </select>
              </label>
              <label className="manage-field">
                <span>Telegram webhook path</span>
                <input
                  value={channelForm.telegram.webhookPath}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      telegram: { ...current.telegram, webhookPath: event.target.value },
                    }))
                  }
                />
              </label>
              <label className="manage-field manage-field--inline">
                <input
                  type="checkbox"
                  checked={channelForm.whatsappCloud.enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      whatsappCloud: { ...current.whatsappCloud, enabled: event.target.checked },
                    }))
                  }
                />
                <span>WhatsApp Cloud</span>
              </label>
              <div className="manage-page__help">
                Official WhatsApp Cloud can bill template messages. Use it only when the official Meta surface is required.
              </div>
              <label className="manage-field">
                <span>WhatsApp webhook path</span>
                <input
                  value={channelForm.whatsappCloud.webhookPath}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      whatsappCloud: { ...current.whatsappCloud, webhookPath: event.target.value },
                    }))
                  }
                />
              </label>
              <label className="manage-field manage-field--inline">
                <input
                  type="checkbox"
                  checked={channelForm.imessage.enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      imessage: { ...current.imessage, enabled: event.target.checked },
                    }))
                  }
                />
                <span>iMessage / BlueBubbles</span>
              </label>
              <label className="manage-field">
                <span>iMessage webhook path</span>
                <input
                  value={channelForm.imessage.webhookPath}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      imessage: { ...current.imessage, webhookPath: event.target.value },
                    }))
                  }
                />
              </label>
              <label className="manage-field manage-field--inline">
                <input
                  type="checkbox"
                  checked={channelForm.whatsappBaileys.enabled}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      whatsappBaileys: { ...current.whatsappBaileys, enabled: event.target.checked },
                    }))
                  }
                />
                <span>WhatsApp Baileys</span>
              </label>
              <div className="manage-page__help">
                Local best-effort WhatsApp session. It is unofficial and not treated as a guaranteed business channel.
              </div>
              <label className="manage-field">
                <span>WhatsApp Baileys session path</span>
                <input
                  value={channelForm.whatsappBaileys.sessionPath}
                  onChange={(event) =>
                    setChannelForm((current) => ({
                      ...current,
                      whatsappBaileys: { ...current.whatsappBaileys, sessionPath: event.target.value },
                    }))
                  }
                />
              </label>
              <div className="manage-form__actions">
                <button type="button" className="manage-page__button" onClick={() => void handleChannelSave()} disabled={saving}>
                  Save channels
                </button>
              </div>
            </div>
          </article>
        </section>

        <section className="manage-grid manage-grid--main">
          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">MCP servers</div>
              <div className="manage-card__hint">JSON config stays explicit</div>
            </div>
            <div className="manage-form">
              <div className="manage-page__help">
                Paste a JSON array of stdio or streamable-http server configs only if you actively use MCP.
              </div>
              <textarea
                className="manage-textarea"
                rows={10}
                value={mcpJson}
                onChange={(event) => setMcpJson(event.target.value)}
              />
              <div className="manage-form__actions">
                <button type="button" className="manage-page__button" onClick={() => void handleMcpSave()} disabled={saving}>
                  Save MCP servers
                </button>
              </div>
            </div>
          </article>

          <article className="manage-card" id="manage-hosted-account" tabIndex={-1}>
            <div className="manage-card__title-row">
              <div className="manage-card__title">Hosted account</div>
              <div className="manage-card__hint">Billing, sync, and device truth only</div>
            </div>
            <div className="manage-list manage-list--dense">
              <SurfaceRow
                label="Identity"
                value={hostedProfileUser?.displayName ?? panelInfo?.account?.displayName ?? 'unavailable'}
                hint={
                  hostedProfileUser?.userId
                    ? `${hostedProfileUser.userId} · ${hostedProfileUser.role}`
                    : panelInfo?.session?.email ?? 'No hosted identity loaded.'
                }
              />
              <SurfaceRow
                label="Account"
                value={panelInfo?.account?.displayName ?? 'unavailable'}
                hint={panelInfo?.account?.accountId ?? 'No hosted account loaded.'}
              />
              <SurfaceRow
                label="Session"
                value={hostedSession?.subscriptionStatus ?? panelInfo?.session?.subscriptionStatus ?? 'unavailable'}
                hint={
                  hostedSession?.subscriptionSyncState
                    ? `${hostedSession.subscriptionSyncState} · ${hostedSession.hostedAccess ? 'hosted enabled' : 'hosted inactive'}`
                    : 'No canonical hosted session loaded.'
                }
              />
              <SurfaceRow
                label="Subscription"
                value={
                  <ControlPlaneStateBadge
                    variant="subscription"
                    state={panelInfo?.account?.subscription.status}
                    compact
                  />
                }
                hint={panelInfo?.account?.subscription.provider ?? 'provider unavailable'}
              />
              <SurfaceRow
                label="Sync"
                value={
                  <ControlPlaneStateBadge
                    variant="sync"
                    state={panelInfo?.account?.subscription.syncState}
                    compact
                  />
                }
                hint={panelInfo?.account?.subscription.providerStatus ?? 'Hosted sync not reported.'}
              />
              <SurfaceRow
                label="Credits"
                value={panelInfo?.account?.balanceCredits ?? '0.00'}
                hint={panelInfo?.account?.usageSnapshot.monthlyCreditsRemaining ?? '0.00 remaining'}
              />
              <SurfaceRow
                label="Devices"
                value={String(hostedSession?.deviceCount ?? panelInfo?.account?.deviceSummary?.total ?? panelInfo?.devices?.length ?? 0)}
                hint={panelInfo?.devices?.[0]?.deviceLabel ?? 'No hosted devices linked yet.'}
              />
              <SurfaceRow
                label="Plan"
                value={panelInfo?.account?.plan?.title ?? 'unknown'}
                hint={panelInfo?.account?.plan ? `${panelInfo.account.plan.monthlyPriceTRY} TRY · ${panelInfo.account.plan.monthlyIncludedCredits} credits` : 'Plan metadata unavailable.'}
              />
              <SurfaceRow
                label="Webhook refs"
                value={String(panelInfo?.account?.processedWebhookEventCount ?? 0)}
                hint="Hosted billing events remain auditable."
              />
            </div>
          </article>

          <article className="manage-card" id="manage-integrations" tabIndex={-1}>
            <div className="manage-card__title-row">
              <div className="manage-card__title">Connected apps</div>
              <div className="manage-card__hint">OAuth-linked surfaces only</div>
            </div>
            <div className="manage-list manage-list--dense">
              {integrationProviders.map((provider) => {
                const integration = connectedIntegrations.find((entry) => entry.provider === provider.provider);
                return (
                  <div
                    key={provider.provider}
                    className="manage-list__row manage-list__row--compact"
                    id={buildControlPlaneAnchorId('manage', 'integration', provider.provider)}
                    tabIndex={-1}
                  >
                    <div>
                      <div className="manage-list__primary">{provider.displayName}</div>
                      <div className="manage-list__secondary">
                        {provider.surfaces.join(' · ')}
                        {integration?.externalAccountLabel ? ` · ${integration.externalAccountLabel}` : ' · Not linked'}
                      </div>
                      <div className="manage-list__small">
                        {provider.configured
                          ? provider.defaultScopes.length
                            ? `${provider.defaultScopes.length} default scopes configured`
                            : 'Ready to connect'
                          : 'OAuth client not configured'}
                      </div>
                    </div>
                    <div className="manage-list__stack">
                      <ControlPlaneStateBadge
                        variant="integration"
                        state={integration?.status ?? 'disconnected'}
                        compact={false}
                      />
                      <div className="manage-form__actions">
                        <button
                          type="button"
                          className="manage-page__button"
                          onClick={() => handleConnectIntegration(provider.provider)}
                          disabled={saving || !provider.configured}
                        >
                          Connect
                        </button>
                        {integration ? (
                          <>
                            <button
                              type="button"
                              className="manage-page__button manage-page__button--ghost"
                              onClick={() => void handleTestIntegration(provider.provider)}
                              disabled={saving || integration.status !== 'connected'}
                            >
                              Test
                            </button>
                            <button
                              type="button"
                              className="manage-page__button manage-page__button--ghost"
                              onClick={() => void handleDisconnectIntegration(integration.integrationId)}
                              disabled={saving}
                            >
                              Disconnect
                            </button>
                          </>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Hosted devices</div>
              <div className="manage-card__hint">Masked, linked, and auditable</div>
            </div>
            <div className="manage-list manage-list--dense">
              {panelInfo?.devices?.length ? (
                panelInfo.devices.slice(0, 5).map((device) => (
                  <div
                    key={device.deviceId}
                    className="manage-list__row manage-list__row--compact"
                    id={buildControlPlaneAnchorId('manage', 'hosted-device', device.deviceId)}
                    tabIndex={-1}
                  >
                    <div>
                      <div className="manage-list__primary">{device.deviceLabel}</div>
                      <div className="manage-list__secondary">
                        {device.lastSeenReleaseTag ? `Release ${device.lastSeenReleaseTag}` : 'No release tag recorded yet.'}
                      </div>
                    </div>
                    <div className="manage-list__stack">
                      <ControlPlaneStateBadge state={device.status} variant="device" compact={false} />
                      <div className="manage-list__small">
                        {new Date(device.linkedAt).toLocaleDateString()}
                        {' · '}
                        {device.lastSeenAt ? new Date(device.lastSeenAt).toLocaleDateString() : 'never'}
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <div className="manage-list__row manage-list__row--compact">No hosted devices linked yet.</div>
              )}
            </div>
          </article>
        </section>

        <section className="manage-grid manage-grid--main">
          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Release stream</div>
              <div className="manage-card__hint">Public updates stay explicit</div>
            </div>
            <div className="manage-list manage-list--dense">
              <SurfaceRow
                label="Current"
                value={releaseInfo?.currentTagName ?? 'unknown'}
                hint={releaseInfo ? `${releaseInfo.currentVersion} on ${releaseInfo.repository}` : 'Local runtime release metadata is unavailable.'}
              />
              <SurfaceRow
                label="Latest"
                value={releaseInfo?.latest?.tagName ?? 'none'}
                hint={releaseInfo?.latest?.publishedAt ?? releaseInfo?.updateMessage ?? 'No publishable release detected yet.'}
              />
              <SurfaceRow
                label="Update status"
                value={releaseInfo?.updateStatus?.replace('_', ' ') ?? 'unavailable'}
                hint={
                  releaseInfo?.updateAvailable
                    ? 'A newer publishable build exists.'
                    : releaseInfo?.publishable
                      ? 'Installed version matches the latest publishable release.'
                      : 'Release checks stay explicit and fail closed.'
                }
              />
            </div>
          </article>

          <article className="manage-card">
            <div className="manage-card__title-row">
              <div className="manage-card__title">Status</div>
              <div className="manage-card__hint">Runtime and control-plane health</div>
            </div>
            <div className="manage-list manage-list--dense">
              <SurfaceRow label="Local runtime" value={status.surfaces.local.ready ? 'Ready' : 'Not ready'} hint={status.surfaces.local.summary} />
              <SurfaceRow label="Shared control plane" value={status.surfaces.shared.ready ? 'Ready' : 'Not ready'} hint={status.surfaces.shared.summary} />
              <SurfaceRow label="Hosted surface" value={status.surfaces.hosted.ready ? 'Ready' : 'Not ready'} hint={status.surfaces.hosted.summary} />
              <SurfaceRow
                label="Billing"
                value={status.controlPlane.health?.connection?.billingMode ?? 'unconfigured'}
                hint={status.controlPlane.health?.connection?.apiBaseUrl ?? 'No billing endpoint configured.'}
              />
              <SurfaceRow
                label="Database pool"
                value={
                  status.controlPlane.health?.database
                    ? status.controlPlane.health.database.mode === 'file_backed'
                      ? 'file-backed'
                      : `${status.controlPlane.health.database.idleCount ?? 0}/${status.controlPlane.health.database.totalCount ?? 0} idle`
                    : 'unavailable'
                }
                hint={
                  status.controlPlane.health?.database
                    ? status.controlPlane.health.database.detail
                    : 'No database health snapshot is available.'
                }
              />
              <SurfaceRow
                label="Sync backlog"
                value={
                  status.controlPlane.health?.syncSummary
                    ? `${status.controlPlane.health.syncSummary.subscriptions.billingPending} pending · ${status.controlPlane.health.syncSummary.subscriptions.syncFailed} failed`
                    : 'unavailable'
                }
                hint={
                  status.controlPlane.health?.syncSummary
                    ? `${status.controlPlane.health.syncSummary.devices.active} devices active`
                    : 'Control-plane sync summary is unavailable.'
                }
              />
              <SurfaceRow
                label="Evaluation trace"
                value={
                  status.controlPlane.health?.evaluationSummary
                    ? `${status.controlPlane.health.evaluationSummary.windowCount} windows`
                    : 'unavailable'
                }
                hint={
                  status.controlPlane.health?.evaluationSummary?.latestSignal
                    ? `${status.controlPlane.health.evaluationSummary.latestSignal.quality} · ${status.controlPlane.health.evaluationSummary.promotionCandidates} promotion candidates`
                    : 'No evaluation signals have been recorded yet.'
                }
              />
              <SurfaceRow
                label="Trace latency"
                value={
                  status.controlPlane.health?.evaluationSummary
                    ? `${status.controlPlane.health.evaluationSummary.averageLatencyMs}ms`
                    : 'unavailable'
                }
                hint={
                  status.controlPlane.health?.evaluationSummary
                    ? `${Math.round(status.controlPlane.health.evaluationSummary.retrievalCoverageRate * 100)}% retrieval coverage · ${Math.round(status.controlPlane.health.evaluationSummary.toolCompletionRate * 100)}% tool completion`
                    : 'Trace coverage is unavailable.'
                }
              />
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

function StatSurfaceCard({
  title,
  icon,
  ready,
  summary,
  detail,
}: {
  title: string;
  icon: React.ReactNode;
  ready: boolean;
  summary: string;
  detail: string;
}) {
  return (
    <article className={ready ? 'manage-surface manage-surface--ready' : 'manage-surface manage-surface--idle'}>
      <div className="manage-surface__top">
        <div className="manage-surface__icon">{icon}</div>
        <div className="manage-surface__status">{ready ? <BadgeCheck size={14} strokeWidth={2.2} /> : <AlertTriangle size={14} strokeWidth={2.2} />}{ready ? 'Ready' : 'Optional'}</div>
      </div>
      <div className="manage-surface__title">{title}</div>
      <div className="manage-surface__summary">{summary}</div>
      <div className="manage-surface__detail">{detail}</div>
    </article>
  );
}

function DomainCard({ domain }: { domain: CapabilityDirectorySnapshot['domains'][number] }) {
  const riskLabel = Object.entries(domain.riskLevelCounts)
    .filter(([, count]) => count > 0)
    .map(([level, count]) => `${formatCapabilityRisk(level as Parameters<typeof formatCapabilityRisk>[0])} ${count}`)
    .join(' · ');

  const approvals = Object.entries(domain.approvalLevelCounts)
    .filter(([, count]) => count > 0)
    .map(([level, count]) => `${formatCapabilityApproval(level as Parameters<typeof formatCapabilityApproval>[0])} ${count}`)
    .join(' · ');
  const sources = Object.entries(domain.sourceCounts)
    .filter(([, count]) => count > 0)
    .map(([source, count]) => `${source.replace('_', ' ')} ${count}`)
    .join(' · ');

  return (
    <div className="manage-domain" id={buildControlPlaneAnchorId('manage', 'capability-domain', domain.category)} tabIndex={-1}>
      <div className="manage-domain__top">
        <div>
          <div className="manage-domain__title">{domain.title}</div>
          <div className="manage-domain__summary">{domain.summary}</div>
        </div>
        <div className="manage-domain__count">{domain.capabilityCount}</div>
      </div>
      <div className="manage-domain__chips">
        <span className="manage-domain__chip">{domain.enabledCapabilityCount} enabled</span>
        <span className="manage-domain__chip">{riskLabel}</span>
        <span className="manage-domain__chip">{approvals}</span>
        <span className="manage-domain__chip">{sources}</span>
      </div>
      <div className="manage-domain__capabilities">
        {domain.libraries.slice(0, 5).map((library) => (
          <span key={library} className="manage-domain__capability">
            {library}
          </span>
        ))}
      </div>
      <div className="manage-domain__capabilities">
        {domain.capabilityIds.slice(0, 5).map((id) => (
          <span key={id} className="manage-domain__capability">
            {id}
          </span>
        ))}
      </div>
    </div>
  );
}

function SurfaceRow({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  const isBadge = React.isValidElement(value);

  return (
    <div className="manage-list__row manage-list__row--compact">
      <div>
        <div className="manage-list__primary">{label}</div>
        <div className="manage-list__secondary">{hint}</div>
      </div>
      <div className="manage-list__stack">
        {isBadge ? value : <div className="manage-list__badge">{value}</div>}
      </div>
    </div>
  );
}
