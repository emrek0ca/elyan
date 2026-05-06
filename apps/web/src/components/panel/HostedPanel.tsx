'use client';

import Link from 'next/link';
import React from 'react';
import { buildControlPlaneAnchorId } from '@/core/control-plane/display';
import type { ControlPlaneHostedPanel } from '@/core/control-plane/types';
import { ControlPlaneStateBadge } from '@/components/control-plane/ControlPlaneStateBadge';

type PanelSection = 'overview' | 'account' | 'billing' | 'devices';

type PanelPayload = {
  ok: boolean;
} & ControlPlaneHostedPanel;

const sections: Array<{ id: PanelSection; label: string; href: string }> = [
  { id: 'overview', label: 'Overview', href: '/panel' },
  { id: 'account', label: 'Account', href: '/panel/account' },
  { id: 'billing', label: 'Billing', href: '/panel/billing' },
  { id: 'devices', label: 'Devices', href: '/panel/devices' },
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

  if (loading) {
    return <div className="panel-page panel-page__empty">Loading hosted panel…</div>;
  }

  if (!payload) {
    return (
      <div className="panel-page panel-page__empty">
        <h1>Hosted unavailable</h1>
        <p>{error ?? 'Sign in to access hosted account state.'}</p>
        <Link href="/auth" className="site-cta">
          Login
        </Link>
      </div>
    );
  }

  const hostedPlan = payload.account.entitlements.hostedAccess;
  const deviceSummary = payload.account.deviceSummary;
  const hostedAccess = payload.session.hostedAccess ?? payload.account.entitlements.hostedAccess;
  const integrations = Object.values(payload.account.integrations ?? {});

  return (
    <div className="panel-page">
      <section className="panel-page__hero">
        <div>
          <div className="site-kicker">Hosted</div>
          <h1 className="site-title">{payload.account.displayName}</h1>
          <p className="site-lead">Account, billing, devices.</p>
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
            <ControlPlaneStateBadge variant="subscription" state={payload.account.subscription.status} compact />
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
          </Link>
        ))}
      </nav>

      {error ? <div className="manage-banner manage-banner--error">{error}</div> : null}

      {section === 'overview' ? (
        <div className="site-grid site-grid--three">
          <article className="site-card" id={buildControlPlaneAnchorId('panel', 'account-state')} tabIndex={-1}>
            <h2>Account state</h2>
            <div className="panel-list">
              <PanelRow label="Email" value={payload.session.email ?? 'unknown'} />
              <PanelRow label="Role" value={payload.session.role ?? 'owner'} />
              <PanelRow label="Plan" value={payload.session.planId ?? payload.account.subscription.planId} />
              <PanelRow label="Subscription" value={payload.session.subscriptionStatus ?? payload.account.subscription.status} />
              <PanelRow label="Sync state" value={payload.session.subscriptionSyncState ?? payload.account.subscription.syncState} />
              <PanelRow label="Hosted access" value={hostedAccess ? 'active' : 'inactive'} />
              <PanelRow label="Credits" value={payload.account.balanceCredits} />
              <PanelRow label="Devices" value={String(deviceSummary.total)} />
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
            <h2>Local</h2>
            <div className="panel-actions">
              <Link href="/download" className="site-cta">
                Install locally
              </Link>
              <Link href="/docs" className="site-secondary-cta">
                Read docs
              </Link>
            </div>
            <p className="panel-copy">Local execution stays on this machine.</p>
          </article>

          <article className="site-card" id={buildControlPlaneAnchorId('panel', 'integrations')} tabIndex={-1}>
            <h2>Connected apps</h2>
            <div className="panel-list">
              <PanelRow label="Linked apps" value={String(integrations.length)} />
              <PanelRow
                label="Active app links"
                value={String(integrations.filter((integration) => integration.status === 'connected').length)}
              />
              <PanelRow
                label="Attention needed"
                value={String(integrations.filter((integration) => integration.status === 'expired' || integration.status === 'error').length)}
              />
              <PanelRow
                label="Latest app state"
                value={
                  integrations[0] ? (
                    <ControlPlaneStateBadge variant="integration" state={integrations[0].status} compact />
                  ) : (
                    'none'
                  )
                }
              />
            </div>
            <div className="panel-history">
              {integrations.length > 0 ? (
                integrations.map((integration) => (
                  <div key={integration.integrationId} className="panel-history__item">
                    <div>
                      <strong>{integration.displayName}</strong>
                      <p>
                        {integration.externalAccountLabel ?? 'Unlinked account'}
                        {integration.surfaces.length ? ` · ${integration.surfaces.join(', ')}` : ''}
                      </p>
                      <ControlPlaneStateBadge variant="integration" state={integration.status} compact />
                    </div>
                    <div className="panel-history__meta">
                      <span>{integration.lastSyncedAt ? new Date(integration.lastSyncedAt).toLocaleString() : 'never'}</span>
                      <span>{integration.lastError ?? 'No errors reported'}</span>
                    </div>
                  </div>
                ))
              ) : (
                <p className="panel-copy">No linked apps.</p>
              )}
            </div>
          </article>

          <article className="site-card" id={buildControlPlaneAnchorId('panel', 'devices')} tabIndex={-1}>
            <h2>Devices</h2>
            <p className="panel-copy">No device required for local mode.</p>
            <div className="panel-list">
              <PanelRow label="Linked devices" value={String(payload.devices.length)} />
              <PanelRow label="Active devices" value={String(deviceSummary.active)} />
              <PanelRow label="Pending devices" value={String(deviceSummary.pending)} />
              <PanelRow
                label="Latest status"
                value={
                  payload.devices[0] ? (
                    <ControlPlaneStateBadge variant="device" state={payload.devices[0].status} compact />
                  ) : (
                    'none'
                  )
                }
              />
            </div>
            <div className="panel-history">
              {payload.devices.length > 0 ? (
                payload.devices.map((device) => (
                  <div key={device.deviceId} className="panel-history__item">
                    <div>
                      <strong>{device.deviceLabel}</strong>
                      <p>{device.lastSeenReleaseTag ?? 'No release tag recorded yet.'}</p>
                      <ControlPlaneStateBadge variant="device" state={device.status} compact />
                      {device.lastSeenReleaseTag ? <span className="panel-history__kind">{device.lastSeenReleaseTag}</span> : null}
                    </div>
                    <div className="panel-history__meta">
                      <span>{new Date(device.linkedAt).toLocaleString()}</span>
                      <span>{device.lastSeenAt ? new Date(device.lastSeenAt).toLocaleString() : 'never'}</span>
                    </div>
                  </div>
                ))
              ) : (
                <p className="panel-copy">No devices linked yet. Install Elyan locally, then run the CLI login command from that machine.</p>
              )}
            </div>
            <div className="panel-actions">
              <Link href="/download" className="site-cta">
                Install locally
              </Link>
              <Link href="/docs/install" className="site-secondary-cta">
                Link from CLI
              </Link>
            </div>
          </article>
        </div>
      ) : null}

      {section === 'account' ? (
        <section className="site-card" id={buildControlPlaneAnchorId('panel', 'account')} tabIndex={-1}>
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
          <article className="site-card" id={buildControlPlaneAnchorId('panel', 'billing-subscription')} tabIndex={-1}>
            <h2>Subscription</h2>
            <div className="panel-list">
              <PanelRow label="Plan" value={payload.account.plan.title} />
              <PanelRow label="Price" value={`${payload.account.plan.monthlyPriceTRY} TRY / month`} />
              <PanelRow label="Included credits" value={payload.account.plan.monthlyIncludedCredits} />
              <PanelRow label="Credits granted" value={payload.account.subscription.creditsGrantedThisPeriod} />
              <PanelRow label="Current period" value={new Date(payload.account.subscription.currentPeriodStartedAt).toLocaleDateString()} />
              <PanelRow label="Renews / ends" value={new Date(payload.account.subscription.currentPeriodEndsAt).toLocaleString()} />
              <PanelRow label="Provider" value={payload.account.subscription.provider} />
              <PanelRow
                label="Subscription state"
                value={<ControlPlaneStateBadge variant="subscription" state={payload.account.subscription.status} compact />}
              />
              <PanelRow
                label="Sync state"
                value={<ControlPlaneStateBadge variant="sync" state={payload.account.subscription.syncState} compact />}
              />
              <PanelRow label="Provider status" value={payload.account.subscription.providerStatus ?? 'unreported'} />
              <PanelRow
                label="Last synced"
                value={payload.account.subscription.lastSyncedAt ? new Date(payload.account.subscription.lastSyncedAt).toLocaleString() : 'never'}
              />
              <PanelRow label="Retry count" value={String(payload.account.subscription.retryCount)} />
              <PanelRow label="Next retry" value={payload.account.subscription.nextRetryAt ? new Date(payload.account.subscription.nextRetryAt).toLocaleString() : 'none'} />
              <PanelRow label="Webhook refs" value={String(payload.account.processedWebhookEventCount)} />
            </div>
            {payload.account.subscription.lastSyncError ? (
              <p className="panel-copy panel-copy--warning">{payload.account.subscription.lastSyncError}</p>
            ) : null}
          </article>

          <article className="site-card" id={buildControlPlaneAnchorId('panel', 'billing-hosted')} tabIndex={-1}>
            <h2>Hosted billing</h2>
            <p className="panel-copy">
              iyzico-backed hosted billing controls managed credits and hosted entitlements. If billing is not configured,
              hosted usage stays inactive and the panel stays honest about the gap.
            </p>
            <div className="panel-list">
              <PanelRow label="Billing state" value={payload.account.subscription.provider} />
              <PanelRow label="Hosted access" value={hostedPlan ? 'enabled' : 'disabled'} />
              <PanelRow label="Credits remaining" value={payload.account.usageSnapshot.monthlyCreditsRemaining} />
              <PanelRow label="Subscription sync" value={payload.account.subscription.syncState} />
              <PanelRow
                label="Hosted state"
                value={<ControlPlaneStateBadge variant="operational" state={hostedPlan ? 'active' : payload.account.subscription.status} compact />}
              />
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
                  !hostedPlan ||
                  (payload.account.subscription.provider === 'iyzico' && payload.account.subscription.syncState !== 'failed')
                }
              >
                {hostedPlan
                  ? payload.account.subscription.syncState === 'failed'
                    ? 'Restart billing'
                    : payload.account.subscription.provider === 'iyzico'
                      ? 'Billing already started'
                      : 'Start billing'
                  : 'Local plan'}
              </button>
              {!hostedPlan ? (
                <Link href="/pricing" className="site-secondary-cta">
                  Compare plans
                </Link>
              ) : null}
            </div>
          </article>
        </section>
      ) : null}

      {section === 'devices' ? (
        <section className="site-grid site-grid--two">
          <article className="site-card" id={buildControlPlaneAnchorId('panel', 'devices-list')} tabIndex={-1}>
            <h2>Linked devices</h2>
            <div className="panel-history">
              {payload.devices.length > 0 ? (
                payload.devices.map((device) => (
                  <div key={device.deviceId} className="panel-history__item">
                    <div>
                      <strong>{device.deviceLabel}</strong>
                      <p>{device.lastSeenReleaseTag ?? 'No release tag recorded yet.'}</p>
                      <ControlPlaneStateBadge variant="device" state={device.status} compact />
                    </div>
                    <div className="panel-history__meta">
                      <span>Linked {new Date(device.linkedAt).toLocaleString()}</span>
                      <span>Last seen {device.lastSeenAt ? new Date(device.lastSeenAt).toLocaleString() : 'never'}</span>
                    </div>
                  </div>
                ))
              ) : (
                <p className="panel-copy">No devices linked yet.</p>
              )}
            </div>
          </article>

          <article className="site-card">
            <h2>Link this machine</h2>
            <p className="panel-copy">Install Elyan locally, run guided setup, then login from the CLI to register this machine.</p>
            <div className="panel-list">
              <PanelRow label="Install" value={<code>/download</code>} />
              <PanelRow label="Setup" value={<code>elyan setup</code>} />
              <PanelRow label="Link" value={<code>elyan login --base-url https://api.elyan.dev</code>} />
              <PanelRow label="Verify" value={<code>elyan whoami</code>} />
            </div>
            <div className="panel-actions">
              <Link href="/download" className="site-cta">
                Install locally
              </Link>
              <Link href="/docs/install" className="site-secondary-cta">
                Read install docs
              </Link>
            </div>
          </article>
        </section>
      ) : null}
    </div>
  );
}

function PanelRow({ label, value }: { label: string; value: React.ReactNode }) {
  const isBadge = React.isValidElement(value);

  return (
    <div className="panel-row">
      <span>{label}</span>
      {isBadge ? value : <strong>{value}</strong>}
    </div>
  );
}
