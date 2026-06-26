import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import path from 'node:path';
import readline from 'node:readline';
import {
  createDegradedBootstrapSnapshot,
  createRuntimeUnavailableResponse,
  ensureRuntimeRequest,
  isRuntimeResponse,
  type BootstrapSnapshot,
  type DesktopPlatform,
  type RuntimeLifecycleEvent,
  type RuntimeRequest,
  type RuntimeResponse,
} from '../shared/protocol';

export interface RuntimeLaunchConfig {
  executable: string;
  args: string[];
  workingDirectory: string;
  mode: 'bundled' | 'python';
  packagedBinaryAvailable: boolean;
  pythonFallbackAvailable: boolean;
}

export interface RuntimeAvailabilitySnapshot {
  packagedBinaryAvailable: boolean;
  pythonFallbackAvailable: boolean;
  rustIndexerManagedByPython: boolean;
}

export interface RuntimeSupervisorOptions {
  desktopRoot: string;
  workspaceRoot: string;
  resourcesPath: string;
  packaged: boolean;
  environment?: NodeJS.ProcessEnv;
  platform: DesktopPlatform;
  readyTimeoutMs?: number;
  requestTimeoutMs?: number;
}

interface PendingRequest {
  request: RuntimeRequest;
  resolve: (response: RuntimeResponse) => void;
  timer: NodeJS.Timeout;
}

export interface RuntimeSupervisorStatus extends RuntimeLifecycleEvent {
  launchMode: RuntimeLaunchConfig['mode'] | 'unavailable';
}

interface ResolveRuntimeLaunchOptions {
  workspaceRoot: string;
  resourcesPath: string;
  packaged: boolean;
  platform: DesktopPlatform;
  environment?: NodeJS.ProcessEnv;
  exists?: (candidate: string) => boolean;
}

function platformFolder(platform: DesktopPlatform): string {
  if (platform === 'darwin') {
    return 'macos';
  }
  if (platform === 'win32') {
    return 'windows';
  }
  return 'linux';
}

function runtimeBinaryName(platform: DesktopPlatform): string {
  return platform === 'win32' ? 'elyan-runtime.exe' : 'elyan-runtime';
}

function pythonExecutableCandidates(options: ResolveRuntimeLaunchOptions): string[] {
  const explicitCandidates = [
    options.environment?.ELYAN_DESKTOP_PYTHON,
    options.environment?.ELYAN_PYTHON_BIN,
  ].filter((candidate): candidate is string => Boolean(candidate && candidate.trim()));
  const workspaceVenvCandidates =
    options.platform === 'win32'
      ? [
          path.join(options.workspaceRoot, '.venv', 'Scripts', 'python.exe'),
          path.join(options.workspaceRoot, 'venv', 'Scripts', 'python.exe'),
        ]
      : [
          path.join(options.workspaceRoot, '.venv', 'bin', 'python3'),
          path.join(options.workspaceRoot, '.venv', 'bin', 'python'),
          path.join(options.workspaceRoot, 'venv', 'bin', 'python3'),
          path.join(options.workspaceRoot, 'venv', 'bin', 'python'),
        ];
  const fallbackCandidates =
    options.platform === 'win32'
      ? ['python']
      : ['python3', 'python', 'python3.14', 'python3.13', 'python3.12', 'python3.11'];
  return [...new Set([...explicitCandidates, ...workspaceVenvCandidates, ...fallbackCandidates])];
}

function pythonCanImportRequests(executable: string): boolean {
  const probe = spawnSync(executable, ['-c', 'import requests'], {
    cwd: process.cwd(),
    encoding: 'utf8',
    shell: false,
    timeout: 5000,
  });
  return probe.status === 0;
}

function isPathLikeCommand(candidate: string): boolean {
  return candidate.includes('/') || candidate.includes('\\');
}

function candidateExists(options: ResolveRuntimeLaunchOptions, candidate: string): boolean {
  const exists = options.exists ?? fs.existsSync;
  return exists(candidate);
}

function commandCanStart(options: ResolveRuntimeLaunchOptions, candidate: string): boolean {
  if (isPathLikeCommand(candidate)) {
    return candidateExists(options, candidate);
  }
  const probe = spawnSync(candidate, ['--version'], {
    cwd: options.workspaceRoot,
    encoding: 'utf8',
    shell: false,
    timeout: 3000,
  });
  return !probe.error;
}

function shouldTrustInjectedExecutable(options: ResolveRuntimeLaunchOptions, candidate: string): boolean {
  return Boolean(options.exists) && isPathLikeCommand(candidate) && candidateExists(options, candidate);
}

function resolvePythonExecutable(options: ResolveRuntimeLaunchOptions): string | null {
  const candidates = pythonExecutableCandidates(options);
  for (const candidate of candidates) {
    if (!candidate) {
      continue;
    }
    if (!commandCanStart(options, candidate)) {
      continue;
    }
    if (shouldTrustInjectedExecutable(options, candidate)) {
      return candidate;
    }
    if (pythonCanImportRequests(candidate)) {
      return candidate;
    }
  }
  for (const candidate of candidates) {
    if (!candidate) {
      continue;
    }
    if (commandCanStart(options, candidate)) {
      return candidate;
    }
  }
  return null;
}

export function resolveRuntimeLaunch(options: ResolveRuntimeLaunchOptions): RuntimeLaunchConfig | null {
  const exists = options.exists ?? fs.existsSync;
  const folder = platformFolder(options.platform);
  const runtimeBinary = runtimeBinaryName(options.platform);
  const packagedBinaryCandidates = [
    path.join(options.resourcesPath, 'runtime', folder, 'elyan-runtime', runtimeBinary),
    path.join(options.resourcesPath, 'runtime', folder, runtimeBinary),
  ];
  const packagedBinaryPath = packagedBinaryCandidates.find((candidate) => exists(candidate));
  const bridgeScript = path.join(options.workspaceRoot, 'runtime', 'bridge.py');
  const pythonFallbackAvailable = exists(bridgeScript);
  const pythonExecutable = resolvePythonExecutable(options);
  if (!options.packaged && pythonFallbackAvailable) {
    if (!pythonExecutable) {
      return null;
    }
    return {
      executable: pythonExecutable,
      args: [bridgeScript],
      workingDirectory: options.workspaceRoot,
      mode: 'python',
      packagedBinaryAvailable: Boolean(packagedBinaryPath),
      pythonFallbackAvailable: true,
    };
  }
  if (packagedBinaryPath) {
    return {
      executable: packagedBinaryPath,
      args: [],
      workingDirectory: path.dirname(packagedBinaryPath),
      mode: 'bundled',
      packagedBinaryAvailable: true,
      pythonFallbackAvailable,
    };
  }
  if (!pythonFallbackAvailable) {
    return null;
  }
  if (!pythonExecutable) {
    return null;
  }
  return {
    executable: pythonExecutable,
    args: [bridgeScript],
    workingDirectory: options.workspaceRoot,
    mode: 'python',
    packagedBinaryAvailable: false,
    pythonFallbackAvailable: true,
  };
}

function nowIso(): string {
  return new Date().toISOString();
}

export class RuntimeSupervisor extends EventEmitter {
  private readonly options: Required<RuntimeSupervisorOptions>;
  private process: ChildProcessWithoutNullStreams | null = null;
  private stdoutReader: readline.Interface | null = null;
  private stderrReader: readline.Interface | null = null;
  private ready = false;
  private manualStop = false;
  private startPromise: Promise<void> | null = null;
  private readyWaiters = new Set<(ready: boolean) => void>();
  private pending = new Map<string, PendingRequest>();
  private restartTimer: NodeJS.Timeout | null = null;
  private restartCount = 0;
  private currentLaunch: RuntimeLaunchConfig | null = null;
  private status: RuntimeSupervisorStatus = {
    phase: 'idle',
    available: false,
    launchMode: 'unavailable',
    reason: undefined,
    lastStartedAt: undefined,
    restartCount: 0,
  };

  constructor(options: RuntimeSupervisorOptions) {
    super();
    this.options = {
      environment: process.env,
      readyTimeoutMs: 7000,
      requestTimeoutMs: 60000,
      ...options,
    };
  }

  getStatus(): RuntimeSupervisorStatus {
    return { ...this.status };
  }

  getAvailability(): RuntimeAvailabilitySnapshot {
    const launch = this.currentLaunch ?? resolveRuntimeLaunch(this.options);
    return {
      packagedBinaryAvailable: Boolean(launch?.packagedBinaryAvailable),
      pythonFallbackAvailable: Boolean(launch?.pythonFallbackAvailable),
      rustIndexerManagedByPython: true,
    };
  }

  async start(): Promise<void> {
    if (this.process || this.startPromise) {
      return this.startPromise ?? Promise.resolve();
    }
    this.startPromise = this.spawnRuntime().finally(() => {
      this.startPromise = null;
    });
    return this.startPromise;
  }

  async bootstrap(): Promise<BootstrapSnapshot> {
    void this.start();
    const ready = await this.waitUntilReady(this.options.readyTimeoutMs);
    if (!ready) {
      const reason = this.status.phase === 'starting' ? 'runtime_starting' : this.status.reason ?? 'runtime_unavailable';
      return createDegradedBootstrapSnapshot(reason);
    }
    const response = await this.request({ capability: 'bootstrap', payload: {} });
    if (!response.ok || !response.result || typeof response.result !== 'object') {
      return createDegradedBootstrapSnapshot(response.error?.code ?? 'runtime_bootstrap_failed');
    }
    return response.result as unknown as BootstrapSnapshot;
  }

  async request(request: RuntimeRequest): Promise<RuntimeResponse> {
    void this.start();
    const ready = await this.waitUntilReady(this.options.readyTimeoutMs);
    if (!ready || !this.process?.stdin.writable) {
      return createRuntimeUnavailableResponse(request, 'Yerel Elyan runtime hazir degil.', 'RUNTIME_NOT_READY');
    }
    const normalized = ensureRuntimeRequest(request);
    const requestKey = normalized.id as string;
    return new Promise<RuntimeResponse>((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(requestKey);
        resolve(
          createRuntimeUnavailableResponse(
            normalized,
            'Yerel Elyan runtime istege zamaninda yanit vermedi.',
            'RUNTIME_TIMEOUT',
          ),
        );
      }, this.options.requestTimeoutMs);
      this.pending.set(requestKey, { request: normalized, resolve, timer });
      try {
        this.process?.stdin.write(`${JSON.stringify(normalized)}\n`);
      } catch {
        clearTimeout(timer);
        this.pending.delete(requestKey);
        resolve(
          createRuntimeUnavailableResponse(normalized, 'Yerel Elyan runtime yazma hatasi verdi.', 'RUNTIME_WRITE_FAILED'),
        );
      }
    });
  }

  async stop(): Promise<void> {
    this.manualStop = true;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    this.resolveReadyWaiters(false);
    this.closeReaders();
    const processRef = this.process;
    this.process = null;
    this.ready = false;
    this.patchStatus({
      phase: 'stopped',
      available: false,
      launchMode: this.currentLaunch?.mode ?? 'unavailable',
      reason: this.status.reason,
    });
    if (processRef && !processRef.killed) {
      processRef.kill('SIGTERM');
    }
    this.flushPending('RUNTIME_STOPPED', 'Yerel Elyan runtime durduruldu.');
  }

  private async spawnRuntime(): Promise<void> {
    this.currentLaunch = resolveRuntimeLaunch(this.options);
    if (!this.currentLaunch) {
      this.patchStatus({
        phase: 'degraded',
        available: false,
        launchMode: 'unavailable',
        reason: 'runtime_launch_missing',
      });
      return;
    }

    this.patchStatus({
      phase: this.restartCount > 0 ? 'restarting' : 'starting',
      available: true,
      launchMode: this.currentLaunch.mode,
      reason: undefined,
    });

    this.manualStop = false;
    try {
      const child = spawn(this.currentLaunch.executable, this.currentLaunch.args, {
        cwd: this.currentLaunch.workingDirectory,
        env: {
          ...this.options.environment,
          PYTHONUNBUFFERED: '1',
        },
        stdio: 'pipe',
      });
      this.process = child;
      this.bindProcess(child);
    } catch (error) {
      this.patchStatus({
        phase: 'degraded',
        available: false,
        launchMode: this.currentLaunch.mode,
        reason: error instanceof Error ? error.message : 'runtime_spawn_failed',
      });
    }
  }

  private bindProcess(child: ChildProcessWithoutNullStreams): void {
    this.stdoutReader = readline.createInterface({ input: child.stdout });
    this.stderrReader = readline.createInterface({ input: child.stderr });

    this.stdoutReader.on('line', (line) => {
      this.handleStdoutLine(line);
    });
    this.stderrReader.on('line', (line) => {
      this.emit('runtime-event', {
        type: 'runtime.stderr',
        source: 'runtime_supervisor',
        level: 'warn',
        message: line,
        at: nowIso(),
      });
    });
    child.on('exit', (code, signal) => {
      this.handleProcessExit(code, signal);
    });
    child.on('error', (error) => {
      this.patchStatus({
        phase: 'degraded',
        available: false,
        launchMode: this.currentLaunch?.mode ?? 'unavailable',
        reason: error.message,
      });
    });
  }

  private handleStdoutLine(line: string): void {
    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch {
      this.emit('runtime-event', {
        type: 'runtime.stdout.invalid_json',
        source: 'runtime_supervisor',
        level: 'warn',
        message: line,
        at: nowIso(),
      });
      return;
    }

    if (!isRuntimeResponse(parsed)) {
      this.emit('runtime-event', {
        type: 'runtime.stdout.unstructured',
        source: 'runtime_supervisor',
        level: 'warn',
        data: parsed as Record<string, unknown>,
        at: nowIso(),
      });
      return;
    }

    if (parsed.capability === 'bridge.ready' && parsed.ok) {
      this.ready = true;
      this.patchStatus({
        phase: 'ready',
        available: true,
        launchMode: this.currentLaunch?.mode ?? 'unavailable',
        reason: undefined,
        lastStartedAt: nowIso(),
      });
      this.resolveReadyWaiters(true);
      return;
    }

    const requestKey = parsed.requestId ?? parsed.id;
    if (requestKey && this.pending.has(requestKey)) {
      const pending = this.pending.get(requestKey);
      if (pending) {
        clearTimeout(pending.timer);
        this.pending.delete(requestKey);
        pending.resolve(parsed);
      }
    }

    for (const event of parsed.events) {
      this.emit('runtime-event', {
        ...event,
        at: typeof event.at === 'string' ? event.at : nowIso(),
      });
    }
  }

  private handleProcessExit(code: number | null, signal: NodeJS.Signals | null): void {
    this.closeReaders();
    this.ready = false;
    const reason = code === null ? `signal_${String(signal ?? 'unknown').toLowerCase()}` : `exit_${code}`;
    this.flushPending('RUNTIME_EXITED', 'Yerel Elyan runtime baglantisi kapandi.');
    this.resolveReadyWaiters(false);
    this.process = null;

    if (this.manualStop) {
      this.patchStatus({
        phase: 'stopped',
        available: false,
        launchMode: this.currentLaunch?.mode ?? 'unavailable',
        reason,
      });
      return;
    }

    this.patchStatus({
      phase: 'restarting',
      available: true,
      launchMode: this.currentLaunch?.mode ?? 'unavailable',
      reason,
    });
    this.restartCount += 1;
    const delayMs = Math.min(4000, 400 * this.restartCount);
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      void this.spawnRuntime();
    }, delayMs);
  }

  private waitUntilReady(timeoutMs: number): Promise<boolean> {
    if (this.ready) {
      return Promise.resolve(true);
    }
    if (this.status.phase === 'degraded' || this.status.phase === 'stopped') {
      return Promise.resolve(false);
    }
    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        this.readyWaiters.delete(handler);
        resolve(false);
      }, timeoutMs);
      const handler = (ready: boolean) => {
        clearTimeout(timer);
        this.readyWaiters.delete(handler);
        resolve(ready);
      };
      this.readyWaiters.add(handler);
    });
  }

  private resolveReadyWaiters(ready: boolean): void {
    for (const waiter of this.readyWaiters) {
      waiter(ready);
    }
    this.readyWaiters.clear();
  }

  private flushPending(code: string, message: string): void {
    for (const [requestId, pending] of this.pending.entries()) {
      clearTimeout(pending.timer);
      pending.resolve(
        createRuntimeUnavailableResponse(
          {
            ...pending.request,
            id: requestId,
          },
          message,
          code,
        ),
      );
    }
    this.pending.clear();
  }

  private closeReaders(): void {
    this.stdoutReader?.removeAllListeners();
    this.stderrReader?.removeAllListeners();
    this.stdoutReader?.close();
    this.stderrReader?.close();
    this.stdoutReader = null;
    this.stderrReader = null;
  }

  private patchStatus(patch: Partial<RuntimeSupervisorStatus>): void {
    this.status = {
      ...this.status,
      ...patch,
      restartCount: this.restartCount,
    };
    this.emit('status', this.getStatus());
  }
}
