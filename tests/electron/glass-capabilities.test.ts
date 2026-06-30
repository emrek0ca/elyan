import { describe, expect, it } from 'vitest';
import type { SystemCapabilities } from '../../src/shared/protocol';
import { createDesktopGlassCapabilities } from '../../src/renderer/platform/glassCapabilities';

function capabilities(nativeAddonAvailable: boolean, vibrancy: boolean): SystemCapabilities {
  return {
    platform: 'darwin',
    windowChrome: {
      customTitlebar: true,
      closeAnimation: true,
      trafficLights: true,
      vibrancy,
      mica: false,
      clientSideDecorations: true,
      tray: true,
      attention: true,
    },
    nativeControl: {
      automation: true,
      screenCapture: true,
      globalShortcuts: true,
      fileSystemAccess: true,
      processInspection: true,
      permissionRequired: true,
      rendererDirectControl: false,
      sideEffectsRequireTaskId: true,
      osPermissionModel: 'macos_privacy_tcc',
      accessibilityPermissionRequired: true,
      screenRecordingPermissionRequired: true,
      inputMonitoringPermissionRequired: true,
      automationPermissionRequired: true,
    },
    runtime: {
      packagedBinaryAvailable: false,
      pythonFallbackAvailable: true,
      rustIndexerManagedByPython: true,
    },
    nativeAddon: {
      available: nativeAddonAvailable,
      failureReason: nativeAddonAvailable ? null : 'native_addon_missing',
      version: nativeAddonAvailable ? 'native' : null,
    },
    nativeDesktop: {} as SystemCapabilities['nativeDesktop'],
  };
}

describe('desktop glass capabilities', () => {
  it('falls back to CSS when the optional macOS native bridge is unavailable', () => {
    const glass = createDesktopGlassCapabilities({
      systemCapabilities: capabilities(false, true),
      prefersReducedMotion: false,
      highContrast: false,
      lowPowerMode: false,
      supportsBackdropFilter: true,
    });

    expect(glass.nativeGlass.available).toBe(false);
    expect(glass.nativeGlass.source).toBe('css_fallback');
    expect(glass.intensityScale).toBe('balanced');
  });

  it('uses native mac glass only when addon vibrancy is available', () => {
    const glass = createDesktopGlassCapabilities({
      systemCapabilities: capabilities(true, true),
      prefersReducedMotion: false,
      highContrast: false,
      lowPowerMode: false,
      supportsBackdropFilter: true,
    });

    expect(glass.nativeGlass.available).toBe(true);
    expect(glass.nativeGlass.source).toBe('swift_bridge');
    expect(glass.intensityScale).toBe('native');
  });
});

