'use client';

import Link from 'next/link';
import React from 'react';
import { buildControlPlaneEvaluationSummary } from '@/core/control-plane/evaluation';
import type { ControlPlaneEvaluationSignal } from '@/core/control-plane/types';

type PanelSection = 'overview' | 'account' | 'billing' | 'usage' | 'notifications';

type PanelPayload = {
  ok: boolean;
  session: {
    email?: string;
    role?: string;
    accountId?: string;
  };
  account: {
    accountId: string;
    displayName: string;
    ownerType: string;
    balanceCredits: string;
    billingCustomerRef?: string;
    status: string;
    subscription: {
      planId: string;
      status: string;
      provider: string;
      syncState: string;
      providerStatus?: string;
      retryCount: number;
      lastSyncedAt?: string;
      nextRetryAt?: string;
      currentPeriodStartedAt: string;
      currentPeriodEndsAt: string;
      creditsGrantedThisPeriod: string;
      lastSyncError?: string;
    };
    plan: {
      title: string;
      summary: string;
      monthlyPriceTRY: string;
      monthlyIncludedCredits: string;
      dailyLimits: {
        hostedRequestsPerDay: number;
        hostedToolActionCallsPerDay: number;
      };
    };
    processedWebhookEventCount: number;
    entitlements: {
      hostedAccess: boolean;
      hostedUsageAccounting: boolean;
      managedCredits: boolean;
      cloudRouting: boolean;
      advancedRouting: boolean;
      teamGovernance: boolean;
      hostedImprovementSignals: boolean;
    };
    usageTotals: Record<string, string>;
    usageSnapshot: {
      dayKey: string;
      resetAt: string;
      dailyRequests: number;
      dailyRequestsLimit: number;
      remainingRequests: number;
      dailyHostedToolActionCalls: number;
      dailyHostedToolActionCallsLimit: number;
      remainingHostedToolActionCalls: number;
      monthlyCreditsRemaining: string;
      monthlyCreditsBurned: string;
      state: 'ok' | 'daily_limit_reached' | 'monthly_credits_exhausted';
    };
    evaluationSignalCount: number;
    recentEvaluationSignals: ControlPlaneEvaluationSignal[];
  };
  ledger: Array<{
    entryId: string;
    kind: string;
    status: string;
    domain?: string;
    creditsDelta: string;
    balanceAfter: string;
    note?: string;
    createdAt: string;
  }>;
  notifications: Array<{
    notificationId: string;
    title: string;
    body: string;
    kind: string;
    level: 'info' | 'warning' | 'error';
    seenAt?: string;
    createdAt: string;
  }>;
  devices: Array<{
    deviceId: string;
    deviceLabel: string;
    status: string;
    linkedAt: string;
    lastSeenAt?: string;
    lastSeenReleaseTag?: string;
    revokedAt?: string;
  }>;
  health: {
    storage: string;
    iyzicoConfigured: boolean;
    connection?: {
      storage?: string;
      hostedReady?: boolean;
      callbackUrl?: string;
      apiBaseUrl?: string;
      billingMode?: 'sandbox' | 'production';
    };
  };
};

const sections: Array<{ id: PanelSection; label: string; href: string }> = [
  { id: 'overview', label: 'Overview', href: '/panel' },
  { id: 'account', label: 'Account', href: '/panel/account' },
  { id: 'billing', label: 'Billing', href: '/panel/billing' },
  { id: 'usage', label: 'Usage', href: '/panel/usage' },
  { id: 'notifications', label: 'Notifications', href: '/panel/notifications' },
];

async function fetchPanel(): Promise<PanelPayload> {
  const response = await fetch('/api/control-plane/panel', {
    credentials: 'include',
    cache: 'no-store',
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? `Failed to load panel (${response.status})`);
  }

  return response.json();
}

export function HostedPanel({ section }: { section: PanelSection }) {
  const [payload, setPayload] = React.useState<PanelPayload | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [busyBilling, setBusyBilling] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setPayload(await fetchPanel());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Failed to load hosted panel');
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function startBilling() {
    try {
      setBusyBilling(true);
      setError(null);
      const response = await fetch('/api/control-plane/billing/iyzico/initialize', {
        method: 'POST',
        credentials: 'include',
      });

      const body = (await response.json().catch(() => null)) as
        | { ok?: boolean; error?: string; initialization?: { paymentPageUrl?: string } }
        | null;

      if (!response.ok || !body?.ok) {
        throw new Error(body?.error ?? 'Billing initialization failed');
      }

      if (body.initialization?.paymentPageUrl) {
        window.location.href = body.initialization.paymentPageUrl;
        return;
      }

      await load();
    } catch (billingError) {
      setError(billingError instanceof Error ? billingError.message : 'Billing initialization failed');
    } finally {
      setBusyBilling(false);
    }
  }

  async function markSeen(notificationId: string) {
    try {
      const response = await fetch(`/api/control-plane/notifications/${notificationId}`, {
        method: 'PATCH',
        credentials: 'include',
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(body?.error ?? 'Notification update failed');
      }

      await load();
    } catch (notificationError) {
      setError(notificationError instanceof Error ? notificationError.message : 'Notification update failed');
    }
  }

  if (loading) {
    return <div className="panel-page panel-page__empty">Loading hosted panel…</div>;
  }

  if (!payload) {
    return (
      <div className="panel-page panel-page__empty">
        <h1>Hosted panel unavailable</h1>
        <p>{error ?? 'Sign in to access hosted account state.'}</p>
        <Link href="/auth" className="site-cta">
          Login
        </Link>
      </div>
    );
  }

  const unseenCount = payload.notifications.filter((entry) => !entry.seenAt).length;
  const evaluationSummary = buildControlPlaneEvaluationSummary(payload.account.recentEvaluationSignals);
  const hostedPlan = payload.account.subscription.planId !== 'local_byok';

  return (
    <div className="panel-page">
      <section className="panel-page__hero">
        <div>
          <div className="site-kicker">Hosted panel</div>
          <h1 className="site-title">{payload.account.displayName}</h1>
          <p className="site-lead">
            Hosted account, credits, subscription state, and announcements. Local runtime state still stays on the user machine.
          </p>
        </div>

        <div className="panel-page__meta">
          <div className="site-card">
            <span className="panel-stat__label">Plan</span>
            <strong className="panel-stat__value">{payload.account.plan.title}</strong>
          </div>
          <div className="site-card">
            <span className="panel-stat__label">Credits</span>
            <strong className="panel-stat__value">{payload.account.balanceCredits}</strong>
          </div>
          <div className="site-card">
            <span className="panel-stat__label">Subscription</span>
            <strong className="panel-stat__value">{payload.account.subscription.status}</strong>
          </div>
        </div>
      </section>

      <nav className="panel-tabs" aria-label="Hosted panel sections">
        {sections.map((entry) => (
          <Link
            key={entry.id}
            href={entry.href}
            className={entry.id === section ? 'panel-tabs__link panel-tabs__link--active' : 'panel-tabs__link'}
          >
            {entry.label}
            {entry.id === 'notifications' && unseenCount > 0 ? <span className="panel-tabs__badge">{unseenCount}</span> : null}
          </Link>
        ))}
      </nav>

      {error ? <div className="manage-banner manage-banner--error">{error}</div> : null}

      {section === 'overview' ? (
        <div className="site-grid site-grid--three">
          <article className="site-card">
            <h2>Account state</h2>
            <div className="panel-list">
              <PanelRow label="Email" value={payload.session.email ?? 'unknown'} />
              <PanelRow label="Role" value={payload.session.role ?? 'owner'} />
              <PanelRow label="Storage" value={payload.health.storage} />
              <PanelRow label="Hosted access" value={payload.account.entitlements.hostedAccess ? 'active' : 'inactive'} />
            </div>
          </article>

          <article className="site-card">
            <h2>Usage window</h2>
            <div className="panel-list">
              <PanelRow label="Daily requests" value={`${payload.account.usageSnapshot.dailyRequests}/${payload.account.usageSnapshot.dailyRequestsLimit}`} />
              <PanelRow label="Requests remaining" value={String(payload.account.usageSnapshot.remainingRequests)} />
              <PanelRow label="Tool calls" value={`${payload.account.usageSnapshot.dailyHostedToolActionCalls}/${payload.account.usageSnapshot.dailyHostedToolActionCallsLimit}`} />
              <PanelRow label="Tool calls remaining" value={String(payload.account.usageSnapshot.remainingHostedToolActionCalls)} />
              <PanelRow label="Monthly credits remaining" value={payload.account.usageSnapshot.monthlyCreditsRemaining} />
              <PanelRow label="Monthly credits burned" value={payload.account.usageSnapshot.monthlyCreditsBurned} />
              <PanelRow label="Reset at" value={new Date(payload.account.usageSnapshot.resetAt).toLocaleString()} />
              <PanelRow label="Limit state" value={payload.account.usageSnapshot.state} />
            </div>
          </article>

          <article className="site-card">
            <h2>Install and runtime</h2>
            <div className="panel-actions">
              <Link href="/download" className="site-cta">Install locally</Link>
              <Link href="/docs" className="site-secondary-cta">Read docs</Link>
            </div>
            <p className="panel-copy">Hosted account controls billing, credits, and web access. The primary runtime still runs locally.</p>
          </article>

          <article className="site-card">
            <h2>Devices</h2>
            <div className="panel-list">
              <PanelRow label="Linked devices" value={String(payload.devices.length)} />
              <PanelRow label="Latest device" value={payload.devices[0]?.deviceLabel ?? 'none'} />
              <PanelRow label="Latest status" value={payload.devices[0]?.status ?? 'none'} />
            </div>
            <div className="panel-history">
              {payload.devices.length > 0 ? payload.devices.map((device) => (
                <div key={device.deviceId} className="panel-history__item">
                  <div>
                    <strong>{device.deviceLabel}</strong>
                    <p>{device.status}</p>
                    {device.lastSeenReleaseTag ? <span className="panel-history__kind">{device.lastSeenReleaseTag}</span> : null}
                  </div>
                  <div className="panel-history__meta">
                    <span>{new Date(device.linkedAt).toLocaleString()}</span>
                    <span>{device.lastSeenAt ? new Date(device.lastSeenAt).toLocaleString() : 'never'}</span>
                  </div>
                </div>
              )) : <p className="panel-copy">No devices linked yet.</p>}
            </div>
          </article>

          <article className="site-card">
            <h2>Learning loop</h2>
            <div className="panel-list">
              <PanelRow label="Signals captured" value={String(payload.account.evaluationSignalCount)} />
              <PanelRow label="Recent window" value={String(evaluationSummary.windowCount)} />
              <PanelRow label="Latest quality" value={evaluationSummary.latestSignal?.quality ?? 'none'} />
              <PanelRow label="Promotion candidates" value={String(evaluationSummary.promotionCandidates)} />
            </div>
            {evaluationSummary.latestSignal ? (
              <p className="panel-copy">
                Latest routing: {evaluationSummary.latestSignal.routingMode}. {evaluationSummary.latestSignal.modelProvider}/{evaluationSummary.latestSignal.modelId}.
                {' '}Sources {evaluationSummary.latestSignal.sourceCount}, citations {evaluationSummary.latestSignal.citationCount}, latency {evaluationSummary.latestSignal.latencyMs}ms.
              </p>
            ) : (
              <p className="panel-copy">
                Hosted improvement signals are structural only. No private prompt or file content is stored in this control plane.
              </p>
            )}
          </article>
        </div>
      ) : null}

      {section === 'account' ? (
        <section className="site-card">
          <h2>Account</h2>
          <div className="panel-list">
            <PanelRow label="Display name" value={payload.account.displayName} />
            <PanelRow label="Account ID" value={payload.account.accountId} />
            <PanelRow label="Owner type" value={payload.account.ownerType} />
            <PanelRow label="Status" value={payload.account.status} />
            <PanelRow label="Billing customer" value={payload.account.billingCustomerRef ?? 'not bound'} />
          </div>
        </section>
      ) : null}

      {section === 'billing' ? (
        <section className="site-grid site-grid--two">
          <article className="site-card">
            <h2>Subscription</h2>
            <div className="panel-list">
              <PanelRow label="Plan" value={payload.account.plan.title} />
              <PanelRow label="Price" value={`${payload.account.plan.monthlyPriceTRY} TRY / month`} />
              <PanelRow label="Included credits" value={payload.account.plan.monthlyIncludedCredits} />
              <PanelRow label="Credits granted" value={payload.account.subscription.creditsGrantedThisPeriod} />
              <PanelRow label="Current period" value={new Date(payload.account.subscription.currentPeriodStartedAt).toLocaleDateString()} />
              <PanelRow label="Renews / ends" value={new Date(payload.account.subscription.currentPeriodEndsAt).toLocaleString()} />
              <PanelRow label="Provider" value={payload.account.subscription.provider} />
              <PanelRow label="Sync state" value={payload.account.subscription.syncState} />
              <PanelRow label="Provider status" value={payload.account.subscription.providerStatus ?? 'unreported'} />
              <PanelRow label="Last synced" value={payload.account.subscription.lastSyncedAt ? new Date(payload.account.subscription.lastSyncedAt).toLocaleString() : 'never'} />
              <PanelRow label="Retry count" value={String(payload.account.subscription.retryCount)} />
              <PanelRow label="Next retry" value={payload.account.subscription.nextRetryAt ? new Date(payload.account.subscription.nextRetryAt).toLocaleString() : 'none'} />
              <PanelRow label="Webhook refs" value={String(payload.account.processedWebhookEventCount)} />
            </div>
            {payload.account.subscription.lastSyncError ? (
              <p className="panel-copy panel-copy--warning">{payload.account.subscription.lastSyncError}</p>
            ) : null}
          </article>

          <article className="site-card">
            <h2>Hosted billing</h2>
            <p className="panel-copy">
              iyzico-backed hosted billing controls managed credits and hosted entitlements. If billing is not configured,
              hosted usage stays inactive and the panel stays honest about the gap.
            </p>
            <div className="panel-list">
              <PanelRow label="Billing mode" value={payload.health.connection?.billingMode ?? 'unconfigured'} />
              <PanelRow label="Billing availability" value={payload.health.iyzicoConfigured ? 'configured' : 'unavailable'} />
              <PanelRow label="API base" value={payload.health.connection?.apiBaseUrl ?? 'not resolved'} />
              <PanelRow label="Callback" value={payload.health.connection?.callbackUrl ?? 'not resolved'} />
              <PanelRow label="Hosted state" value={payload.account.entitlements.hostedAccess ? 'active' : payload.account.subscription.syncState} />
            </div>
            <p className="panel-copy">
              {!hostedPlan
                ? 'This plan is local-only. Hosted billing stays unavailable by design.'
                : payload.account.subscription.syncState === 'synced'
                  ? 'Hosted billing is active and webhook deliveries are already accounted for.'
                  : payload.account.subscription.syncState === 'pending'
                    ? 'Checkout is already initialized. Complete the payment page, then wait for the webhook.'
                    : payload.account.subscription.syncState === 'failed'
                      ? 'Billing needs a fresh initialization after the last webhook failure.'
                      : 'Start hosted billing only when you want elyan.dev access and managed credits.'}
            </p>
            <div className="panel-actions">
              <button
                type="button"
                className="site-cta panel-button"
                onClick={() => void startBilling()}
                disabled={
                  busyBilling ||
                  !payload.health.iyzicoConfigured ||
                  !hostedPlan ||
                  (payload.account.subscription.provider === 'iyzico' &&
                    payload.account.subscription.syncState !== 'failed')
                }
              >
                {hostedPlan
                  ? payload.health.iyzicoConfigured
                    ? payload.account.subscription.syncState === 'failed'
                      ? 'Restart billing'
                      : payload.account.subscription.provider === 'iyzico'
                        ? 'Billing already started'
                        : 'Start billing'
                    : 'Billing not configured'
                  : 'Local plan'}
              </button>
              {!payload.account.entitlements.hostedAccess ? (
                <Link href="/pricing" className="site-secondary-cta">
                  Compare plans
                </Link>
              ) : null}
            </div>
          </article>
        </section>
      ) : null}

      {section === 'usage' ? (
        <div className="site-grid site-grid--two">
          <article className="site-card">
            <h2>Usage snapshot</h2>
            <div className="panel-list">
              <PanelRow label="Daily requests" value={`${payload.account.usageSnapshot.dailyRequests}/${payload.account.usageSnapshot.dailyRequestsLimit}`} />
              <PanelRow label="Requests remaining" value={String(payload.account.usageSnapshot.remainingRequests)} />
              <PanelRow label="Tool calls" value={`${payload.account.usageSnapshot.dailyHostedToolActionCalls}/${payload.account.usageSnapshot.dailyHostedToolActionCallsLimit}`} />
              <PanelRow label="Tool calls remaining" value={String(payload.account.usageSnapshot.remainingHostedToolActionCalls)} />
              <PanelRow label="Monthly credits remaining" value={payload.account.usageSnapshot.monthlyCreditsRemaining} />
              <PanelRow label="Monthly credits burned" value={payload.account.usageSnapshot.monthlyCreditsBurned} />
              <PanelRow label="Reset at" value={new Date(payload.account.usageSnapshot.resetAt).toLocaleString()} />
              <PanelRow label="Limit state" value={payload.account.usageSnapshot.state} />
            </div>
          </article>

          <article className="site-card">
            <h2>Usage totals</h2>
            <div className="panel-list">
              {Object.entries(payload.account.usageTotals).map(([key, value]) => (
                <PanelRow key={key} label={key} value={value} />
              ))}
            </div>
          </article>

          <article className="site-card">
            <h2>Ledger</h2>
            <div className="panel-history">
              {payload.ledger.length > 0 ? payload.ledger.map((entry) => (
                <div key={entry.entryId} className="panel-history__item">
                  <div>
                    <strong>{entry.kind}</strong>
                    <p>{entry.note ?? entry.domain ?? 'hosted usage event'}</p>
                  </div>
                  <div className="panel-history__meta">
                    <span>{entry.creditsDelta}</span>
                    <span>{new Date(entry.createdAt).toLocaleString()}</span>
                  </div>
                </div>
              )) : <p className="panel-copy">No hosted usage yet.</p>}
            </div>
          </article>
        </div>
      ) : null}

      {section === 'notifications' ? (
        <section className="site-card">
          <h2>Notifications</h2>
          <div className="panel-history">
            {payload.notifications.length > 0 ? payload.notifications.map((entry) => (
              <div key={entry.notificationId} className={`panel-history__item panel-history__item--${entry.level}`}>
                <div>
                  <strong>{entry.title}</strong>
                  <p>{entry.body}</p>
                  <span className="panel-history__kind">{entry.kind}</span>
                </div>
                <div className="panel-history__meta">
                  <span>{new Date(entry.createdAt).toLocaleString()}</span>
                  {!entry.seenAt ? (
                    <button type="button" className="site-secondary-cta panel-button" onClick={() => void markSeen(entry.notificationId)}>
                      Mark seen
                    </button>
                  ) : (
                    <span>Seen</span>
                  )}
                </div>
              </div>
            )) : <p className="panel-copy">No announcements yet.</p>}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function PanelRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
