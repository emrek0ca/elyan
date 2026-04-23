import { describe, expect, it } from 'vitest';
import { buildRuntimeSurfaceSnapshot } from '@/core/runtime-surface';

describe('runtime surface snapshot', () => {
  it('keeps search state explicit when search is disabled', () => {
    const snapshot = buildRuntimeSurfaceSnapshot({
      localModelCount: 1,
      searchEnabled: false,
      searchAvailable: false,
      controlPlaneReady: false,
      hostedAuthConfigured: false,
      hostedBillingConfigured: false,
    });

    expect(snapshot.surfaces.local.detail).toContain('disabled');
    expect(snapshot.nextSteps[1]).toContain('disabled');
  });
});
