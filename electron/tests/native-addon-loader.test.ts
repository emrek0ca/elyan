import { describe, expect, it } from 'vitest';
import { loadNativeWindowAddon } from '../src/main/native/addon-loader';

describe('native addon loader', () => {
  it('returns a fallback runtime snapshot when addon is missing', () => {
    const addon = loadNativeWindowAddon({
      desktopRoot: '/workspace/electron',
      resourcesPath: '/workspace/resources',
      packaged: false,
      platform: 'darwin',
    });

    expect(addon.status.available).toBe(false);
    expect(addon.runtimeSnapshot.platform).toBe('darwin');
    expect(addon.runtimeSnapshot.permissions.accessibility.required).toBe(true);
    expect(addon.runtimeSnapshot.processes.items).toEqual([]);
    expect(addon.runtimeSnapshot.lastErrorCode).toBe('native_addon_missing');
  });
});
