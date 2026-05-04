import { describe, expect, it } from 'vitest';
import { shouldFetchHostedControlPlane } from '@/core/control-plane/hosted-fetch';

function statusInput(hostedReady: boolean, hostedConnectionReady = false) {
  return {
    surfaces: {
      local: { key: 'local' as const, label: 'Local runtime', ready: true, summary: '', detail: '' },
      shared: { key: 'shared' as const, label: 'Shared control plane', ready: false, summary: '', detail: '' },
      hosted: { key: 'hosted' as const, label: 'Hosted surface', ready: hostedReady, summary: '', detail: '' },
    },
    controlPlane: {
      health: {
        connection: { hostedReady: hostedConnectionReady },
      },
    },
  };
}

describe('manage hosted control-plane fetch gating', () => {
  it('skips optional hosted fetches when hosted state is unavailable', () => {
    expect(shouldFetchHostedControlPlane(statusInput(false))).toBe(false);
  });

  it('allows optional hosted fetches when hosted state is ready', () => {
    expect(shouldFetchHostedControlPlane(statusInput(true))).toBe(true);
    expect(shouldFetchHostedControlPlane(statusInput(false, true))).toBe(true);
  });
});
