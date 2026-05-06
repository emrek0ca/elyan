import path from 'path';
import PQueue from 'p-queue';
import type { DispatchTask } from '../types';
import {
  appendJsonLine,
  ensureTaskWorkspace,
  resolveTaskWorkspacePaths,
  readTaskWorkspaceRecoverySnapshot,
  type RuntimeTraceEvent,
  type TaskRuntimeState,
  withTaskWorkspaceLock,
  writeJsonAtomic,
} from './workspace';

export type DispatchRuntimeContext = {
  taskId: string;
  workspacePath: string;
  browserSessionPath: string;
  terminalSessionPath: string;
  approvalPath: string;
  approvalCheckpointPath: string;
  tracePath: string;
  observabilityTracePath: string;
  statePath: string;
  recoveryState: 'fresh' | 'resumed' | 'recovered';
  signal: AbortSignal;
};

type ScheduledTask = {
  taskId: string;
  runner: () => Promise<void>;
};

export class DispatchRuntimeCoordinator {
  private readonly queue = new PQueue({ concurrency: 1 });
  private readonly scheduledTaskIds = new Set<string>();
  private readonly controllers = new Map<string, AbortController>();
  private readonly controllerTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly recoveryStates = new Map<string, 'fresh' | 'resumed' | 'recovered'>();
  private bootstrapped = false;

  async bootstrap(tasks: DispatchTask[], recover: (taskId: string) => Promise<void>) {
    if (this.bootstrapped) {
      return;
    }

    this.bootstrapped = true;
    await Promise.all(tasks.map((task) => this.ensureTaskWorkspace(task)));
    const recoverableTasks = tasks.filter(
      (task) =>
        task.status === 'queued' ||
        task.status === 'planning' ||
        task.status === 'executing' ||
        task.status === 'exporting' ||
        (task.status === 'waiting_approval' && task.approval.state === 'approved')
    );

    for (const task of recoverableTasks) {
      this.recoveryStates.set(task.id, 'recovered');
      await this.enqueueTask(task.id, () => recover(task.id));
    }
  }

  async ensureTaskWorkspace(task: DispatchTask) {
    const paths = resolveTaskWorkspacePaths(task.id);
    await ensureTaskWorkspace(paths);
    const snapshot = await readTaskWorkspaceRecoverySnapshot(paths);
    const recoveryState = this.recoveryStates.get(task.id) ?? (snapshot.state ? 'recovered' : 'fresh');
    this.recoveryStates.set(task.id, recoveryState);
    await this.writeRuntimeState(task.id, {
      taskId: task.id,
      workspacePath: paths.root,
      status: task.status,
      progress: task.progress,
      updatedAt: task.updatedAt,
      approvalState: task.approval.state,
      recoveryState,
      browserSessionPath: paths.browserSessionPath,
      tracePath: paths.runtimeTracePath,
      observabilityTracePath: paths.observabilityTracePath,
      notes: [...task.notes],
      metadata: {
        source: task.source,
        title: task.title,
        objective: task.objective,
        requestedArtifacts: task.requestedArtifacts,
      },
    });
    return paths;
  }

  async enqueueTask(taskId: string, runner: () => Promise<void>) {
    if (this.scheduledTaskIds.has(taskId)) {
      return;
    }

    this.scheduledTaskIds.add(taskId);
    const scheduled: ScheduledTask = { taskId, runner };

    return this.queue.add(async () => {
      try {
        await scheduled.runner();
      } finally {
        this.scheduledTaskIds.delete(taskId);
      }
    });
  }

  hasTaskScheduled(taskId: string) {
    return this.scheduledTaskIds.has(taskId);
  }

  getRecoveryState(taskId: string) {
    return this.recoveryStates.get(taskId) ?? 'fresh';
  }

  setRecoveryState(taskId: string, state: 'fresh' | 'resumed' | 'recovered') {
    this.recoveryStates.set(taskId, state);
  }

  createExecutionContext(taskId: string, timeoutMs: number): DispatchRuntimeContext {
    const paths = resolveTaskWorkspacePaths(taskId);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), Math.max(1_000, timeoutMs));
    this.controllers.set(taskId, controller);
    this.controllerTimers.set(taskId, timeout);

    controller.signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timeout);
      },
      { once: true }
    );

    return {
      taskId,
      workspacePath: paths.root,
      browserSessionPath: paths.browserSessionPath,
      terminalSessionPath: path.join(paths.root, 'terminal', 'session.json'),
      approvalPath: paths.approvalPath,
      approvalCheckpointPath: paths.approvalPath,
      tracePath: paths.runtimeTracePath,
      observabilityTracePath: paths.observabilityTracePath,
      statePath: paths.statePath,
      recoveryState: this.getRecoveryState(taskId),
      signal: controller.signal,
    };
  }

  releaseExecutionContext(taskId: string) {
    this.controllers.get(taskId)?.abort();
    this.controllers.delete(taskId);
    const timeout = this.controllerTimers.get(taskId);
    if (timeout) {
      clearTimeout(timeout);
      this.controllerTimers.delete(taskId);
    }
  }

  abortTask(taskId: string) {
    this.releaseExecutionContext(taskId);
  }

  async withTaskWorkspace<T>(taskId: string, run: (paths: ReturnType<typeof resolveTaskWorkspacePaths>) => Promise<T>) {
    const paths = resolveTaskWorkspacePaths(taskId);
    await ensureTaskWorkspace(paths);
    return withTaskWorkspaceLock(paths.root, async () => run(paths));
  }

  async recordLifecycleEvent(
    taskId: string,
    event: Pick<RuntimeTraceEvent, 'kind' | 'status' | 'progress' | 'note' | 'data'>
  ) {
    const paths = resolveTaskWorkspacePaths(taskId);
    await ensureTaskWorkspace(paths);
    await appendJsonLine(paths.runtimeTracePath, {
      timestamp: new Date().toISOString(),
      taskId,
      ...event,
    } satisfies RuntimeTraceEvent);
  }

  async writeRuntimeState(taskId: string, state: TaskRuntimeState) {
    const paths = resolveTaskWorkspacePaths(taskId);
    await ensureTaskWorkspace(paths);
    await writeJsonAtomic(paths.statePath, state);
  }

  async persistApprovalCheckpoint(task: DispatchTask, reason: string) {
    const paths = resolveTaskWorkspacePaths(task.id);
    await ensureTaskWorkspace(paths);
    await writeJsonAtomic(paths.approvalPath, {
      taskId: task.id,
      status: task.status,
      approval: task.approval,
      reason,
      recoveryState: this.getRecoveryState(task.id),
      updatedAt: new Date().toISOString(),
    });
    await this.recordLifecycleEvent(task.id, {
      kind: 'checkpoint',
      status: task.status,
      progress: task.progress,
      note: reason,
      data: {
        approvalState: task.approval.state,
      },
    });
  }

  async persistObservabilityTrace(taskId: string, trace: unknown) {
    const paths = resolveTaskWorkspacePaths(taskId);
    await ensureTaskWorkspace(paths);
    await writeJsonAtomic(paths.observabilityTracePath, trace);
  }

  async cancelTask(taskId: string) {
    this.releaseExecutionContext(taskId);
    this.recoveryStates.set(taskId, 'fresh');
    await this.recordLifecycleEvent(taskId, {
      kind: 'lifecycle',
      note: 'Task cancellation requested.',
    });
  }
}

let singletonDispatchRuntimeCoordinator: DispatchRuntimeCoordinator | null = null;

export function getDispatchRuntimeCoordinator() {
  if (!singletonDispatchRuntimeCoordinator) {
    singletonDispatchRuntimeCoordinator = new DispatchRuntimeCoordinator();
  }

  return singletonDispatchRuntimeCoordinator;
}
