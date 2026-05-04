export type ControlPlaneBadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

export type ControlPlaneStatePresentation = {
  label: string;
  tone: ControlPlaneBadgeTone;
  detail: string;
};

type ConnectionState = 'active' | 'expiring' | 'rotate' | 'revoked' | 'expired' | 'stale' | 'missing' | 'invalid';
type IntegrationState = 'disconnected' | 'connecting' | 'connected' | 'expired' | 'error' | 'revoked';
type DeviceState = 'pending' | 'active' | 'revoked' | 'expired';
type SubscriptionStatus = 'trialing' | 'active' | 'past_due' | 'suspended' | 'canceled';
type SyncState = 'unbound' | 'pending' | 'synced' | 'failed';
type OperationalStatus = SubscriptionStatus | 'billing_pending' | 'sync_failed';

const connectionStateMap: Record<ConnectionState, ControlPlaneStatePresentation> = {
  active: {
    label: 'Active',
    tone: 'success',
    detail: 'Configured and ready.',
  },
  expiring: {
    label: 'Expiring',
    tone: 'warning',
    detail: 'Configured, but nearing expiry.',
  },
  rotate: {
    label: 'Rotate',
    tone: 'warning',
    detail: 'Secret rotation is recommended.',
  },
  revoked: {
    label: 'Revoked',
    tone: 'danger',
    detail: 'Access was revoked.',
  },
  expired: {
    label: 'Expired',
    tone: 'neutral',
    detail: 'Token or binding has expired.',
  },
  stale: {
    label: 'Stale',
    tone: 'warning',
    detail: 'Configured, but not recently refreshed.',
  },
  missing: {
    label: 'Missing',
    tone: 'neutral',
    detail: 'Not configured yet.',
  },
  invalid: {
    label: 'Invalid',
    tone: 'danger',
    detail: 'Configuration failed validation.',
  },
};

const deviceStateMap: Record<DeviceState, ControlPlaneStatePresentation> = {
  pending: {
    label: 'Pending',
    tone: 'accent',
    detail: 'Link is waiting to complete.',
  },
  active: {
    label: 'Active',
    tone: 'success',
    detail: 'Device is linked and healthy.',
  },
  revoked: {
    label: 'Revoked',
    tone: 'danger',
    detail: 'Device access was revoked.',
  },
  expired: {
    label: 'Expired',
    tone: 'neutral',
    detail: 'Device link expired.',
  },
};

const integrationStateMap: Record<IntegrationState, ControlPlaneStatePresentation> = {
  disconnected: {
    label: 'Disconnected',
    tone: 'neutral',
    detail: 'OAuth connection is not active.',
  },
  connecting: {
    label: 'Connecting',
    tone: 'accent',
    detail: 'OAuth authorization is in progress.',
  },
  connected: {
    label: 'Connected',
    tone: 'success',
    detail: 'OAuth connection is active.',
  },
  expired: {
    label: 'Expired',
    tone: 'warning',
    detail: 'Connection token needs reauthorization.',
  },
  error: {
    label: 'Error',
    tone: 'danger',
    detail: 'Provider reported a failure.',
  },
  revoked: {
    label: 'Revoked',
    tone: 'danger',
    detail: 'Connection was disconnected.',
  },
};

const subscriptionStatusMap: Record<SubscriptionStatus, ControlPlaneStatePresentation> = {
  trialing: {
    label: 'Trialing',
    tone: 'accent',
    detail: 'Trial access is still active.',
  },
  active: {
    label: 'Active',
    tone: 'success',
    detail: 'Subscription is active.',
  },
  past_due: {
    label: 'Past due',
    tone: 'warning',
    detail: 'Payment is overdue.',
  },
  suspended: {
    label: 'Suspended',
    tone: 'danger',
    detail: 'Access is paused until billing is resolved.',
  },
  canceled: {
    label: 'Canceled',
    tone: 'neutral',
    detail: 'Subscription was canceled.',
  },
};

const syncStateMap: Record<SyncState, ControlPlaneStatePresentation> = {
  unbound: {
    label: 'Unbound',
    tone: 'neutral',
    detail: 'No billing binding is attached.',
  },
  pending: {
    label: 'Billing pending',
    tone: 'warning',
    detail: 'Checkout or webhook completion is still in progress.',
  },
  synced: {
    label: 'Synced',
    tone: 'success',
    detail: 'Provider and control plane agree.',
  },
  failed: {
    label: 'Sync failed',
    tone: 'danger',
    detail: 'The last billing sync attempt failed.',
  },
};

const operationalStatusMap: Record<OperationalStatus, ControlPlaneStatePresentation> = {
  trialing: {
    label: 'Trialing',
    tone: 'accent',
    detail: 'Trial access is still active.',
  },
  active: {
    label: 'Active',
    tone: 'success',
    detail: 'Hosted access is active.',
  },
  past_due: {
    label: 'Past due',
    tone: 'warning',
    detail: 'The invoice is overdue.',
  },
  suspended: {
    label: 'Suspended',
    tone: 'danger',
    detail: 'Hosted access is paused.',
  },
  canceled: {
    label: 'Canceled',
    tone: 'neutral',
    detail: 'Subscription is canceled.',
  },
  billing_pending: {
    label: 'Billing pending',
    tone: 'warning',
    detail: 'Checkout or webhook flow is pending.',
  },
  sync_failed: {
    label: 'Sync failed',
    tone: 'danger',
    detail: 'Control-plane sync needs attention.',
  },
};

function normalizeText(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function toPresentation<T extends string>(
  value: string | undefined,
  map: Record<T, ControlPlaneStatePresentation>,
  fallbackTone: ControlPlaneBadgeTone = 'neutral'
): ControlPlaneStatePresentation {
  if (!value) {
    return {
      label: 'Unknown',
      tone: fallbackTone,
      detail: 'No state was reported.',
    };
  }

  const normalized = value as T;
  const presentation = map[normalized];
  if (presentation) {
    return presentation;
  }

  return {
    label: value.replace(/_/g, ' '),
    tone: fallbackTone,
    detail: 'No description is available for this state.',
  };
}

export function describeConnectionLifecycle(state?: string) {
  return toPresentation(state, connectionStateMap);
}

export function describeIntegrationStatus(state?: string) {
  return toPresentation(state, integrationStateMap, 'warning');
}

export function describeDeviceLifecycle(state?: string) {
  return toPresentation(state, deviceStateMap, 'warning');
}

export function describeSubscriptionStatus(status?: string) {
  return toPresentation(status, subscriptionStatusMap, 'warning');
}

export function describeSubscriptionSyncState(syncState?: string) {
  return toPresentation(syncState, syncStateMap);
}

export function describeOperationalStatus(status?: string) {
  return toPresentation(status, operationalStatusMap, 'warning');
}

export function buildControlPlaneAnchorId(...parts: Array<string | number | null | undefined>) {
  const value = parts
    .map((part) => String(part ?? ''))
    .map((part) => normalizeText(part).replace(/ /g, '-'))
    .filter(Boolean)
    .join('-');

  return value || 'control-plane-section';
}

export function findMatchingConnectionTarget(
  query: { capabilityId: string; title: string },
  records: Array<{ kind: string; id: string; title: string; scope: string }>
) {
  const normalizedQueryId = normalizeText(query.capabilityId);
  const normalizedQueryTitle = normalizeText(query.title);

  for (const record of records) {
    const recordText = normalizeText(`${record.kind} ${record.id} ${record.title} ${record.scope}`);

    if (!recordText) {
      continue;
    }

    if (
      recordText.includes(normalizedQueryId) ||
      normalizedQueryId.includes(recordText) ||
      (normalizedQueryTitle.length >= 4 && recordText.includes(normalizedQueryTitle)) ||
      (normalizedQueryTitle.length >= 4 && normalizedQueryTitle.includes(recordText))
    ) {
      return {
        targetId: buildControlPlaneAnchorId('manage', 'connection', record.kind, record.id),
        label: record.title,
      };
    }
  }

  return undefined;
}
