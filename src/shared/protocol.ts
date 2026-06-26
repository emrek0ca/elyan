export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonMap = { [key: string]: JsonValue };

export interface SafeError {
  code: string;
  message: string;
}

export interface RuntimeEvent {
  type?: string;
  source?: string;
  title?: string;
  message?: string;
  level?: 'info' | 'warn' | 'error' | 'progress';
  data?: JsonValue;
  at?: string;
}

export interface RuntimeArtifact {
  id?: string;
  kind?: string;
  name?: string;
  mimeType?: string;
  path?: string;
  url?: string;
  data?: JsonValue;
}

export interface RuntimeRequest {
  id?: string;
  taskId?: string;
  capability: string;
  payload?: JsonMap;
}

export interface RuntimeResponse {
  id: string;
  taskId: string;
  ok: boolean;
  capability: string;
  result: JsonValue | null;
  events: RuntimeEvent[];
  artifacts: RuntimeArtifact[];
  error: SafeError | null;
  durationMs: number;
  requestId?: string;
}

export type DesktopPlatform = 'darwin' | 'win32' | 'linux';

export interface WindowState {
  isFocused: boolean;
  isVisible: boolean;
  isMaximized: boolean;
  isMinimized: boolean;
  isFullScreen: boolean;
  isClosing: boolean;
  platform: DesktopPlatform;
}

export interface NativeAddonStatus {
  available: boolean;
  failureReason: string | null;
  version: string | null;
}

export interface NativeDesktopPermissionState {
  required: boolean;
  granted: boolean | null;
  status: 'granted' | 'denied' | 'required' | 'not_required' | 'unknown';
  source?: string;
  lastCheckedAt?: string;
  settingsDeepLinkAvailable?: boolean;
}

export interface NativeDesktopProcessInfo {
  pid: number;
  name: string;
  executablePath?: string;
  bundleId?: string;
  frontmost?: boolean;
}

export interface NativeDesktopWindowInfo {
  available: boolean;
  appName: string;
  windowTitle: string;
  processId: number | null;
  executablePath?: string;
  bundleId?: string;
  source?: string;
  confidence?: number;
}

export interface ScreenObservationElement {
  id: string;
  type: 'button' | 'input' | 'text' | 'icon' | 'checkbox' | 'menu' | 'image' | 'unknown';
  text: string;
  bbox: {
    x: number;
    y: number;
    w: number;
    h: number;
  };
  confidence: number;
  source: 'ocr' | 'cv' | 'accessibility' | 'bbox';
}

export interface ScreenObservation {
  screenshotPath: string;
  width: number;
  height: number;
  monitorId: string;
  scaleFactor: number;
  capturedAt: string;
  activeApp: string;
  activeWindow: string;
  elements: ScreenObservationElement[];
}

export interface OperatorActionProposal {
  actionType: string;
  targetText?: string;
  elementType?: string;
  requiresApproval?: boolean;
  riskReason?: string;
}

export interface OperatorExecutionResult {
  kind: string;
  runId?: string;
  status?: string;
  stepIndex?: number;
  attemptCount?: number;
  stopped?: boolean;
  stopReason?: string;
  actionType?: string;
  verification?: {
    ok: boolean;
    checkedAt?: string;
    reason?: string;
  };
  operator?: {
    runId: string;
    status: string;
    currentStep: number;
    requiresApproval: boolean;
    activeApp: string;
    activeWindow: string;
    lastVerificationOk: boolean;
    observationId?: string;
    stopReason?: string;
  };
}

export interface NativeDesktopOperatorSnapshot {
  available: boolean;
  mode: 'macos_first' | 'scaffold_only';
  screenObservationReady: boolean;
  accessibilityReady: boolean;
  inputControlReady: boolean;
  emergencyStopAvailable: boolean;
  failSafeCornerAbort: boolean;
  playwrightReady?: boolean;
  browserFirstReady?: boolean;
  operatorResolutionMode?: string;
  lastTargetSource?: string;
  lastVerificationSource?: string;
  lastTargetConfidence?: number;
  activeRunSummary: JsonMap;
  lastErrorCode: string;
}

export interface NativeDesktopSnapshot {
  available: boolean;
  source: 'native_addon' | 'fallback';
  collectedAt: string;
  platform: DesktopPlatform;
  osPermissionModel: string;
  processInspectionAvailable: boolean;
  activeWindowAvailable: boolean;
  permissionProbeAvailable: boolean;
  globalShortcutsAvailable: boolean;
  screenCaptureAvailable: boolean;
  permissions: {
    accessibility: NativeDesktopPermissionState;
    screenRecording: NativeDesktopPermissionState;
    inputMonitoring: NativeDesktopPermissionState;
    automation: NativeDesktopPermissionState;
  };
  processes: {
    available: boolean;
    total: number;
    items: NativeDesktopProcessInfo[];
  };
  activeWindow: NativeDesktopWindowInfo;
  operator: NativeDesktopOperatorSnapshot;
  lastErrorCode: string;
}

export interface SystemCapabilities {
  platform: DesktopPlatform;
  windowChrome: {
    customTitlebar: boolean;
    closeAnimation: boolean;
    trafficLights: boolean;
    vibrancy: boolean;
    mica: boolean;
    clientSideDecorations: boolean;
    tray: boolean;
    attention: boolean;
  };
  nativeControl: {
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
  };
  runtime: {
    packagedBinaryAvailable: boolean;
    pythonFallbackAvailable: boolean;
    rustIndexerManagedByPython: boolean;
  };
  nativeAddon: NativeAddonStatus;
  nativeDesktop: NativeDesktopSnapshot;
}

export interface BootstrapSnapshot {
  state: JsonMap;
  workspace: JsonMap;
  conversations: JsonMap[];
  runtime: JsonMap;
  backend: JsonMap;
  localModels: JsonMap;
}

export interface RuntimeLifecycleEvent {
  phase: 'idle' | 'starting' | 'ready' | 'degraded' | 'restarting' | 'stopped';
  available: boolean;
  reason?: string;
  lastStartedAt?: string;
  restartCount?: number;
}

export function createId(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}_${Date.now().toString(36)}_${random}`;
}

export function ensureRuntimeRequest(request: RuntimeRequest): RuntimeRequest {
  return {
    id: request.id ?? createId('req'),
    taskId: request.taskId ?? createId('task'),
    capability: String(request.capability || '').trim(),
    payload: request.payload ?? {},
  };
}

export function isRuntimeResponse(value: unknown): value is RuntimeResponse {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Partial<RuntimeResponse>;
  return (
    typeof candidate.id === 'string' &&
    typeof candidate.taskId === 'string' &&
    typeof candidate.ok === 'boolean' &&
    typeof candidate.capability === 'string' &&
    Array.isArray(candidate.events) &&
    Array.isArray(candidate.artifacts) &&
    typeof candidate.durationMs === 'number'
  );
}

export function createRuntimeUnavailableResponse(
  request: RuntimeRequest,
  message = 'Yerel Elyan runtime su anda kullanilamiyor.',
  code = 'RUNTIME_UNAVAILABLE',
): RuntimeResponse {
  const normalized = ensureRuntimeRequest(request);
  return {
    id: normalized.id as string,
    taskId: normalized.taskId as string,
    ok: false,
    capability: normalized.capability,
    result: null,
    events: [],
    artifacts: [],
    error: { code, message },
    durationMs: 0,
    requestId: normalized.id,
  };
}

export function createDegradedBootstrapSnapshot(reason: string): BootstrapSnapshot {
  return {
    state: {
      conversation: {
        activeId: '',
        items: [],
      },
    },
    workspace: {
      projects: [],
    },
    conversations: [],
    runtime: {
      ok: false,
      runtimeReady: false,
      runtimeLifecycleState: 'degraded',
      runtimeTransport: {
        mode: 'stdio',
        connected: false,
        lastErrorCode: reason,
        lastXRequestId: '',
      },
      runtimeCapabilities: [],
      runtimeCapabilityStates: {},
      runtimeCapabilityGroups: {},
      dependencyStatus: {},
      taskInbox: [],
    },
    backend: {
      ok: false,
      reason,
    },
    localModels: {
      ok: false,
      reason,
    },
  };
}

export function createPreviewBootstrapSnapshot(): BootstrapSnapshot {
  return createDegradedBootstrapSnapshot('runtime_unavailable');
}
