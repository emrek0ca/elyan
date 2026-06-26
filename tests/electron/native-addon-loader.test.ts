import { describe, expect, it } from 'vitest';
import { loadNativeWindowAddon } from '../../src/main/native/addon-loader';

describe('native addon loader', () => {
  it('returns a fallback runtime snapshot when addon is missing', () => {
    const addon = loadNativeWindowAddon({
      desktopRoot: '/workspace',
      resourcesPath: '/workspace/resources',
      packaged: false,
      platform: 'darwin',
    });

    expect(addon.status.available).toBe(false);
    expect(addon.runtimeSnapshot.platform).toBe('darwin');
    expect(addon.runtimeSnapshot.permissions.accessibility.required).toBe(true);
    expect(addon.runtimeSnapshot.permissions.inputMonitoring.source).toBeTruthy();
    expect(addon.runtimeSnapshot.permissions.automation.settingsDeepLinkAvailable).toBe(true);
    expect(addon.runtimeSnapshot.processes.items).toEqual([]);
    expect(addon.runtimeSnapshot.operator.mode).toBe('macos_first');
    expect(addon.runtimeSnapshot.operator.failSafeCornerAbort).toBe(true);
    expect(addon.runtimeSnapshot.operator.browserFirstReady).toBe(false);
    expect(addon.runtimeSnapshot.lastErrorCode).toBe('native_addon_missing');
  });
});
