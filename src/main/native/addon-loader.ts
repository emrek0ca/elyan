import fs from 'node:fs';
import path from 'node:path';
import type { DesktopPlatform, NativeAddonStatus, NativeDesktopSnapshot } from '../../shared/protocol';

export interface NativeWindowChromeCapabilities {
  customTitlebar: boolean;
  closeAnimation: boolean;
  trafficLights: boolean;
  vibrancy: boolean;
  mica: boolean;
  clientSideDecorations: boolean;
  tray: boolean;
  attention: boolean;
  titlebarInset: number;
  trafficLightOffsetX: number;
  trafficLightOffsetY: number;
  automation: boolean;
  screenCapture: boolean;
  globalShortcuts: boolean;
  fileSystemAccess: boolean;
  processInspection: boolean;
  permissionRequired: boolean;
  rendererDirectControl: boolean;
  sideEffectsRequireTaskId: boolean;
  osPermissionModel: string;
  accessibilityPermissionRequired: boolean;
  screenRecordingPermissionRequired: boolean;
  inputMonitoringPermissionRequired: boolean;
  automationPermissionRequired: boolean;
}

interface NativeWindowAddonModule {
  version?: string;
  getPlatformCapabilities?: () => Partial<NativeWindowChromeCapabilities>;
  getWindowMetrics?: () => Partial<NativeWindowChromeCapabilities>;
  getSystemIntegrationStatus?: () => Partial<NativeWindowChromeCapabilities>;
  getDesktopCapabilitySnapshot?: () => Partial<NativeDesktopSnapshot>;
}

export interface NativeWindowAddon {
  status: NativeAddonStatus;
  capabilities: NativeWindowChromeCapabilities;
  runtimeSnapshot: NativeDesktopSnapshot;
}

interface LoadNativeWindowAddonOptions {
  desktopRoot: string;
  resourcesPath: string;
  packaged: boolean;
  platform: DesktopPlatform;
}

function fallbackCapabilities(platform: DesktopPlatform): NativeWindowChromeCapabilities {
  return {
    customTitlebar: true,
    closeAnimation: true,
    trafficLights: platform === 'darwin',
    vibrancy: platform === 'darwin',
    mica: platform === 'win32',
    clientSideDecorations: true,
    tray: platform !== 'linux',
    attention: true,
    titlebarInset: platform === 'darwin' ? 18 : 16,
    trafficLightOffsetX: 18,
    trafficLightOffsetY: 16,
    automation: true,
    screenCapture: true,
    globalShortcuts: true,
    fileSystemAccess: true,
    processInspection: true,
    permissionRequired: true,
    rendererDirectControl: false,
    sideEffectsRequireTaskId: true,
    osPermissionModel:
      platform === 'darwin' ? 'macos_privacy_tcc' : platform === 'win32' ? 'windows_user_session' : 'linux_desktop_portal_or_x11',
    accessibilityPermissionRequired: platform === 'darwin',
    screenRecordingPermissionRequired: platform === 'darwin' || platform === 'linux',
    inputMonitoringPermissionRequired: platform === 'darwin' || platform === 'linux',
    automationPermissionRequired: platform === 'darwin' || platform === 'linux',
  };
}

function candidatePaths(options: LoadNativeWindowAddonOptions): string[] {
  const fileName = 'window_tools.node';
  const devPath = path.join(options.desktopRoot, 'native', 'window_tools', 'build', 'Release', fileName);
  const packagedPath = path.join(options.resourcesPath, 'native', 'window_tools', fileName);
  return options.packaged ? [packagedPath, devPath] : [devPath, packagedPath];
}

function fallbackPermissionState(required: boolean): NativeDesktopSnapshot['permissions']['accessibility'] {
  const status = required ? 'required' : 'not_required';
  return {
    required,
    granted: required ? null : true,
    status,
    source: 'fallback',
    settingsDeepLinkAvailable: required,
    lastCheckedAt: new Date().toISOString(),
  };
}

function fallbackRuntimeSnapshot(
  platform: DesktopPlatform,
  capabilities: NativeWindowChromeCapabilities,
  addonAvailable: boolean,
): NativeDesktopSnapshot {
  const accessibility = fallbackPermissionState(capabilities.accessibilityPermissionRequired);
  const screenRecording = fallbackPermissionState(capabilities.screenRecordingPermissionRequired);
  const inputMonitoring = fallbackPermissionState(capabilities.inputMonitoringPermissionRequired);
  const automation = fallbackPermissionState(capabilities.automationPermissionRequired);
  return {
    available: addonAvailable,
    source: addonAvailable ? 'native_addon' : 'fallback',
    collectedAt: new Date().toISOString(),
    platform,
    osPermissionModel: capabilities.osPermissionModel,
    processInspectionAvailable: capabilities.processInspection,
    activeWindowAvailable: false,
    permissionProbeAvailable: true,
    globalShortcutsAvailable: capabilities.globalShortcuts,
    screenCaptureAvailable: capabilities.screenCapture,
    permissions: {
      accessibility,
      screenRecording,
      inputMonitoring,
      automation,
    },
    processes: {
      available: capabilities.processInspection,
      total: 0,
      items: [],
    },
    activeWindow: {
      available: false,
      appName: '',
      windowTitle: '',
      processId: null,
      executablePath: '',
      bundleId: '',
      source: 'fallback',
      confidence: 0,
    },
    operator: {
      available: platform === 'darwin',
      mode: platform === 'darwin' ? 'macos_first' : 'scaffold_only',
      screenObservationReady: false,
      accessibilityReady: false,
      inputControlReady: false,
      emergencyStopAvailable: false,
      failSafeCornerAbort: true,
      playwrightReady: false,
      browserFirstReady: false,
      operatorResolutionMode: '',
      lastTargetSource: '',
      lastVerificationSource: '',
      lastTargetConfidence: 0,
      activeRunSummary: {},
      lastErrorCode: addonAvailable ? '' : 'native_addon_missing',
    },
    lastErrorCode: addonAvailable ? '' : 'native_addon_missing',
  };
}

export function loadNativeWindowAddon(options: LoadNativeWindowAddonOptions): NativeWindowAddon {
  const fallback = fallbackCapabilities(options.platform);
  for (const candidate of candidatePaths(options)) {
    if (!fs.existsSync(candidate)) {
      continue;
    }
    try {
      // eslint-disable-next-line @typescript-eslint/no-var-requires
      const loaded = require(candidate) as NativeWindowAddonModule;
      const capabilities = {
        ...fallback,
        ...(loaded.getPlatformCapabilities?.() ?? {}),
        ...(loaded.getWindowMetrics?.() ?? {}),
        ...(loaded.getSystemIntegrationStatus?.() ?? {}),
      };
      const runtimeSnapshot = {
        ...fallbackRuntimeSnapshot(options.platform, capabilities, true),
        ...(loaded.getDesktopCapabilitySnapshot?.() ?? {}),
        collectedAt: new Date().toISOString(),
        source: 'native_addon',
      } satisfies NativeDesktopSnapshot;
      return {
        status: {
          available: true,
          failureReason: null,
          version: typeof loaded.version === 'string' ? loaded.version : 'native',
        },
        capabilities,
        runtimeSnapshot,
      };
    } catch (error) {
      return {
        status: {
          available: false,
          failureReason: error instanceof Error ? error.message : 'native_addon_load_failed',
          version: null,
        },
        capabilities: fallback,
        runtimeSnapshot: {
          ...fallbackRuntimeSnapshot(options.platform, fallback, false),
          lastErrorCode: 'native_addon_load_failed',
        },
      };
    }
  }

  return {
    status: {
      available: false,
      failureReason: 'native_addon_missing',
      version: null,
    },
    capabilities: fallback,
    runtimeSnapshot: fallbackRuntimeSnapshot(options.platform, fallback, false),
  };
}
