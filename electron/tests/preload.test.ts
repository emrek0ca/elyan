import { describe, expect, it, vi } from 'vitest';
import { createDesktopApi } from '../src/preload/createDesktopApi';
import type { DesktopSubscriptionChannel } from '../src/shared/channels';

describe('preload desktop api', () => {
  it('round-trips runtime requests through typed transport', async () => {
    const invoke = vi.fn(async () => ({ ok: true }));
    const api = createDesktopApi({
      invoke,
      on() {
        return () => {};
      },
    });

    const response = await api.request({ capability: 'runtime.status', payload: {} });
    expect(response).toEqual({ ok: true });
    expect(invoke).toHaveBeenCalledWith('elyan:request', { capability: 'runtime.status', payload: {} });
  });

  it('rejects unsupported subscription channels', () => {
    const api = createDesktopApi({
      async invoke() {
        return {};
      },
      on(_channel: DesktopSubscriptionChannel) {
        return () => {};
      },
    });

    expect(() => api.subscribe('bad-channel' as DesktopSubscriptionChannel, () => {})).toThrow('Unsupported subscription channel');
  });
});
