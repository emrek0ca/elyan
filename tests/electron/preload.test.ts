import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { createDesktopApi } from '../../src/preload/createDesktopApi';
import type { DesktopSubscriptionChannel } from '../../src/shared/channels';

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

  it('keeps the real Electron preload out of sandbox fallback mode', () => {
    const source = fs.readFileSync(path.resolve(__dirname, '../../src/main/window-manager.ts'), 'utf8');

    expect(source).toContain('contextIsolation: true');
    expect(source).toContain('nodeIntegration: false');
    expect(source).toContain('sandbox: false');
  });
});
