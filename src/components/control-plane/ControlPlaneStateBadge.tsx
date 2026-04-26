'use client';
import {
  describeConnectionLifecycle,
  describeDeviceLifecycle,
  describeIntegrationStatus,
  describeOperationalStatus,
  describeSubscriptionStatus,
  describeSubscriptionSyncState,
  type ControlPlaneStatePresentation,
} from '@/core/control-plane/display';

type ControlPlaneStateBadgeVariant = 'connection' | 'subscription' | 'sync' | 'operational' | 'device' | 'integration';

function resolvePresentation(state: string | undefined, variant: ControlPlaneStateBadgeVariant): ControlPlaneStatePresentation {
  if (variant === 'subscription') {
    return describeSubscriptionStatus(state);
  }

  if (variant === 'sync') {
    return describeSubscriptionSyncState(state);
  }

  if (variant === 'operational') {
    return describeOperationalStatus(state);
  }

  if (variant === 'device') {
    return describeDeviceLifecycle(state);
  }

  if (variant === 'integration') {
    return describeIntegrationStatus(state);
  }

  return describeConnectionLifecycle(state);
}

export function ControlPlaneStateBadge({
  state,
  variant,
  compact = false,
}: {
  state?: string;
  variant: ControlPlaneStateBadgeVariant;
  compact?: boolean;
}) {
  const presentation = resolvePresentation(state, variant);

  return (
    <span
      className={[
        'control-state-badge',
        `control-state-badge--${presentation.tone}`,
        compact ? 'control-state-badge--compact' : '',
      ]
        .filter(Boolean)
        .join(' ')}
      title={presentation.detail}
    >
      <span className="control-state-badge__label">{presentation.label}</span>
      {!compact ? <span className="control-state-badge__detail">{presentation.detail}</span> : null}
    </span>
  );
}
