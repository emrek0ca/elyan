import { executeInteractionText } from '@/core/interaction/orchestrator';
import { buildExecutionSurfaceSnapshot, buildOrchestrationPlan } from '@/core/orchestration';
import { decideExecution, type ExecutionDecision } from '@/core/decision/engine';
import { decidePolicy } from '@/core/control/policy-engine';
import { buildReasoningPlanSummary } from '@/core/reasoning';
import { classifyInteractionIntent } from '@/core/interaction/intent';
import { getOperatorRunStore } from '@/core/operator';
import { registry } from '@/core/providers';
import type { RunTraceReport } from '@/core/observability/run-trace';
import type { DispatchExecutionContext, DispatchStatusSnapshot, DispatchTask, DispatchTaskRequest } from './types';
import {
  buildDispatchTaskId,
  createDispatchTaskRecord,
  getDispatchTaskStore,
  normalizeDispatchTaskRequest,
} from './store';
import { buildDispatchStatusSnapshot } from './status';
import { inferDispatchProgress, mapDispatchSourceToOperatorSource } from './types';
import { getDispatchRuntimeCoordinator, persistTaskWorkspaceArtifacts } from './runtime';

function nowIso() {
  return new Date().toISOString();
}

function safeTrim(value: string | undefined | null) {
  return value?.trim() ?? '';
}

function stringifyMetadataValue(value: unknown) {
  if (typeof value === 'string') {
    return value;
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function normalizeStringMetadata(metadata: Record<string, unknown> | undefined) {
  if (!metadata) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(metadata).map(([key, value]) => [key, stringifyMetadataValue(value)])
  );
}

function deriveObjective(text: string) {
  const trimmed = safeTrim(text);
  return trimmed.slice(0, 120) || 'Remote task';
}

function deriveProgress(task: Pick<DispatchTask, 'status' | 'taskIntent' | 'mode' | 'progressDetail'>) {
  return inferDispatchProgress(task);
}

function queryComplexity(query: string, mode: ExecutionDecision['mode']) {
  const normalized = query.replace(/\s+/g, ' ').trim();
  const length = normalized.length;
  const hasMultipleClauses =
    /[;,.!?].*[;,.!?]/.test(normalized) || /\b(and|then|after|before|while|plus)\b/i.test(normalized);

  if (mode === 'fast') {
    return length > 120 || hasMultipleClauses ? 'medium' : 'low';
  }

  if (mode === 'research') {
    return length > 180 || hasMultipleClauses ? 'high' : 'medium';
  }

  if (mode === 'quantum') {
    return length > 220 || hasMultipleClauses ? 'high' : 'medium';
  }

  return length > 180 || hasMultipleClauses ? 'high' : length > 100 ? 'medium' : 'low';
}

function detectApprovalReason(plan: ReturnType<typeof buildOrchestrationPlan>, decision: ExecutionDecision) {
  if (!plan.executionPolicy.requiresConfirmation) {
    return undefined;
  }

  return (
    plan.executionPolicy.fallbackReason ||
    decision.reasoning.find((entry) => /approval|confirm|danger|write|terminal|browser/i.test(entry)) ||
    'Task requires approval before any bounded side effect can continue.'
  );
}

function shouldPauseForApproval(plan: ReturnType<typeof buildOrchestrationPlan>, task: DispatchTask) {
  return plan.executionPolicy.requiresConfirmation && task.approval.state !== 'approved';
}

function resolveResponseModelProvider(modelId?: string) {
  if (!modelId) {
    return undefined;
  }

  try {
    return registry.resolveModel(modelId).provider.id;
  } catch {
    return modelId.includes(':') ? modelId.split(':', 1)[0] : modelId;
  }
}

function isProcessableTask(task: DispatchTask) {
  return (
    task.status === 'queued' ||
    task.status === 'planning' ||
    task.status === 'executing' ||
    task.status === 'exporting' ||
    (task.status === 'waiting_approval' && task.approval.state === 'approved')
  );
}

function mergeArtifacts(existing: DispatchTask['artifacts'], next: DispatchTask['artifacts']) {
  const seen = new Set(existing.map((artifact) => artifact.id));
  return [
    ...existing,
    ...next.filter((artifact) => {
      if (seen.has(artifact.id)) {
        return false;
      }

      seen.add(artifact.id);
      return true;
    }),
  ];
}

function buildRuntimeState(
  task: DispatchTask,
  workspacePaths: {
    root: string;
    browserSessionPath: string;
    runtimeTracePath: string;
    observabilityTracePath: string;
    approvalPath: string;
  },
  recoveryState?: 'fresh' | 'resumed' | 'recovered'
) {
  return {
    taskId: task.id,
    workspacePath: workspacePaths.root,
    status: task.status,
    progress: task.progress,
    updatedAt: task.updatedAt,
    checkpoint: task.approval.state !== 'none' ? task.approval.state : undefined,
    approvalState: task.approval.state,
    recoveryState,
    browserSessionPath: workspacePaths.browserSessionPath,
    tracePath: workspacePaths.runtimeTracePath,
    observabilityTracePath: workspacePaths.observabilityTracePath,
    notes: [...task.notes],
    metadata: {
      source: task.source,
      title: task.title,
      objective: task.objective,
      taskIntent: task.taskIntent,
      progressDetail: task.progressDetail,
      modelId: task.modelId,
      modelProvider: task.modelProvider,
      runId: task.runId,
      status: task.status,
    },
  };
}

export class DispatchService {
  private readonly store = getDispatchTaskStore();
  private readonly runtime = getDispatchRuntimeCoordinator();
  private drainScheduled = false;
  private bootstrapped = false;

  async bootstrap() {
    if (this.bootstrapped) {
      return;
    }

    this.bootstrapped = true;
    const tasks = await this.store.list();
    await this.runtime.bootstrap(tasks, async (taskId) => {
      await this.processTask(taskId);
    });

    const bootstrappableTasks = tasks.filter(
      (task) => task.status === 'planning' || (task.status === 'queued' && task.autoStart !== false)
    );
    if (bootstrappableTasks.length > 0) {
      this.scheduleDrain();
    }
  }

  async listTasks() {
    await this.bootstrap();
    return this.store.list();
  }

  async getTask(taskId: string) {
    await this.bootstrap();
    return this.store.get(taskId);
  }

  async submitTask(request: DispatchTaskRequest, context: DispatchExecutionContext = {}) {
    await this.bootstrap();
    const normalized = normalizeDispatchTaskRequest(request);
    const taskId = buildDispatchTaskId();
    const task = createDispatchTaskRecord({
      id: taskId,
      source: normalized.source,
      title: normalized.title,
      objective: deriveObjective(normalized.title),
      text: normalized.text,
      mode: normalized.mode,
      autoStart: normalized.autoStart,
      accountId: context.accountId,
      spaceId: context.spaceId,
      conversationId: request.conversationId,
      messageId: request.messageId,
      userId: request.userId,
      displayName: request.displayName,
      requestedArtifacts: normalized.requestedArtifacts,
      metadata: {
        ...normalized.metadata,
        dispatchRequestedArtifacts: normalized.requestedArtifacts,
        dispatchAutoStart: normalized.autoStart,
      },
    });
    await this.store.create(task);
    await this.runtime.ensureTaskWorkspace(task);
    if (task.autoStart) {
      this.scheduleDrain();
    }
    return task;
  }

  async resumeTask(taskId: string, note?: string) {
    await this.bootstrap();
    const current = await this.store.get(taskId);
    if (!current) {
      return null;
    }

    if (current.status === 'completed' || current.status === 'failed') {
      return current;
    }

    const now = nowIso();
    this.runtime.setRecoveryState(taskId, 'resumed');
    const nextTask: DispatchTask = {
      ...current,
      status: 'queued',
      autoStart: true,
      progress: deriveProgress({
        ...current,
        status: 'queued',
      }),
      updatedAt: now,
      queuedAt: current.queuedAt ?? now,
      approval: {
        ...current.approval,
        state: current.approval.required ? 'approved' : current.approval.state,
        resolvedAt: current.approval.required ? now : current.approval.resolvedAt,
        resolvedBy: current.approval.required ? 'remote-user' : current.approval.resolvedBy,
      },
      notes: [...current.notes, note ? `Resume note: ${note}` : 'Task resumed.'],
      error: undefined,
    };
    await this.store.write(nextTask);
    await this.runtime.recordLifecycleEvent(taskId, {
      kind: 'recovery',
      status: nextTask.status,
      progress: nextTask.progress,
      note: note ? `Task resumed: ${note}` : 'Task resumed.',
    });
    const workspacePaths = await this.runtime.ensureTaskWorkspace(nextTask);
    await this.runtime.writeRuntimeState(taskId, buildRuntimeState(nextTask, workspacePaths, this.runtime.getRecoveryState(taskId)));
    this.scheduleDrain();
    return nextTask;
  }

  async cancelTask(taskId: string, note?: string) {
    await this.bootstrap();
    const current = await this.store.get(taskId);
    if (!current) {
      return null;
    }

    if (current.status === 'completed' || current.status === 'failed') {
      return current;
    }

    const now = nowIso();
    const nextTask: DispatchTask = {
      ...current,
      status: 'failed',
      progress: 'thinking',
      updatedAt: now,
      failedAt: now,
      cancelledAt: now,
      cancellationRequestedAt: current.cancellationRequestedAt ?? now,
      error: note ? `Task cancelled: ${note}` : 'Task cancelled by user.',
      notes: [...current.notes, note ? `Cancelled: ${note}` : 'Cancelled by user.'],
    };
    await this.store.write(nextTask);
    await this.runtime.cancelTask(taskId);
    const workspacePaths = await this.runtime.ensureTaskWorkspace(nextTask);
    await this.runtime.writeRuntimeState(taskId, buildRuntimeState(nextTask, workspacePaths, this.runtime.getRecoveryState(taskId)));
    await this.runtime.recordLifecycleEvent(taskId, {
      kind: 'lifecycle',
      status: nextTask.status,
      progress: nextTask.progress,
      note: nextTask.error,
      data: {
        cancellationRequestedAt: nextTask.cancellationRequestedAt,
        cancelledAt: nextTask.cancelledAt,
        recoveryState: this.runtime.getRecoveryState(taskId),
      },
    });
    await this.runtime.cleanupTaskWorkspace(taskId).catch(() => undefined);
    return nextTask;
  }

  async statusSnapshot(): Promise<DispatchStatusSnapshot> {
    await this.bootstrap();
    return buildDispatchStatusSnapshot(await this.store.list());
  }

  private scheduleDrain() {
    if (this.drainScheduled) {
      return;
    }

    this.drainScheduled = true;
    queueMicrotask(() => {
      this.drainScheduled = false;
      this.drainQueue().catch((error) => {
        console.warn('Dispatch queue drain failed', error);
      });
    });
  }

  private async drainQueue() {
    const queuedTasks = (await this.store.list()).filter(
      (task) => task.status === 'queued' && task.autoStart !== false && !this.runtime.hasTaskScheduled(task.id)
    );
    if (queuedTasks.length === 0) {
      return;
    }

    const nextTask = queuedTasks[0];
    if (!nextTask) {
      return;
    }

    await this.runtime.enqueueTask(nextTask.id, async () => {
      await this.processTask(nextTask.id);
    });

    const remainingQueued = (await this.store.list()).some((task) => task.status === 'queued');
    if (remainingQueued) {
      this.scheduleDrain();
    }
  }

  private async processTask(taskId: string) {
    const current = await this.store.get(taskId);
    if (!current || !isProcessableTask(current)) {
      return;
    }

    let cleanupTerminalWorkspace = false;
    await this.runtime.withTaskWorkspace(taskId, async (workspacePaths) => {
      const refreshedCurrent = (await this.store.get(taskId)) ?? current;
      if (!isProcessableTask(refreshedCurrent)) {
        return;
      }

      const recoveryState = this.runtime.getRecoveryState(taskId);
      if (refreshedCurrent.status === 'executing' && recoveryState === 'recovered') {
        cleanupTerminalWorkspace = await this.failTask(
          refreshedCurrent,
          'Recovered task was executing during restart; failing closed to avoid duplicate side effects.',
          workspacePaths,
          { cleanupWorkspace: true, traceKind: 'recovery' }
        );
        return;
      }

      if (refreshedCurrent.status === 'exporting') {
        cleanupTerminalWorkspace = await this.failTask(
          refreshedCurrent,
          'Recovered task was exporting during restart; failing closed to avoid duplicate side effects.',
          workspacePaths,
          { cleanupWorkspace: true, traceKind: 'recovery' }
        );
        return;
      }

      const now = nowIso();
      const initialProgress = deriveProgress({
        ...refreshedCurrent,
        status: 'planning',
      });

      const planningTask: DispatchTask = {
        ...refreshedCurrent,
        status: 'planning',
        progress: initialProgress,
        planningAt: refreshedCurrent.planningAt ?? now,
        updatedAt: now,
        notes: [...refreshedCurrent.notes, 'Planning remote execution path.'],
      };
      await this.store.write(planningTask);
      await this.runtime.writeRuntimeState(taskId, buildRuntimeState(planningTask, workspacePaths, this.runtime.getRecoveryState(taskId)));
      await this.runtime.recordLifecycleEvent(taskId, {
        kind: 'lifecycle',
        status: planningTask.status,
        progress: planningTask.progress,
        note: 'Planning remote execution path.',
        data: {
          recoveryState: this.runtime.getRecoveryState(taskId),
        },
      });

      const surface = buildExecutionSurfaceSnapshot();
      const classification = classifyInteractionIntent(refreshedCurrent.text, refreshedCurrent.mode);
      const plan = buildOrchestrationPlan(refreshedCurrent.text, refreshedCurrent.mode, surface);
      const decision = await decideExecution({
        query: refreshedCurrent.text,
        taskType: plan.taskIntent,
        requestedModelId: refreshedCurrent.modelId,
        spaceId: refreshedCurrent.spaceId ?? refreshedCurrent.accountId,
        routingMode: plan.routingMode,
        reasoningDepth: plan.reasoningDepth,
      });
      const policy = decidePolicy({
        decision,
        taskType: plan.taskIntent,
        queryComplexity: queryComplexity(refreshedCurrent.text, decision.mode),
      });

      const nextProgress = deriveProgress({
        ...planningTask,
        taskIntent: plan.taskIntent,
        mode: refreshedCurrent.mode,
        status: 'executing',
      });

      const approvalReason = detectApprovalReason(plan, decision);
      if (shouldPauseForApproval(plan, planningTask) && approvalReason) {
        const waitingTask: DispatchTask = {
          ...planningTask,
          status: 'waiting_approval',
          progress: 'thinking',
          waitingApprovalAt: nowIso(),
          approval: {
            state: 'pending',
            required: true,
            reason: approvalReason,
            requestedAt: nowIso(),
          },
          taskIntent: plan.taskIntent,
          planSummary: buildReasoningPlanSummary(plan, classification.intent),
          progressDetail: approvalReason,
          updatedAt: nowIso(),
          notes: [...planningTask.notes, approvalReason],
        };
        await this.store.write(waitingTask);
        await this.runtime.persistApprovalCheckpoint(waitingTask, approvalReason);
        await this.runtime.writeRuntimeState(taskId, buildRuntimeState(waitingTask, workspacePaths, this.runtime.getRecoveryState(taskId)));
        await this.runtime.recordLifecycleEvent(taskId, {
          kind: 'checkpoint',
          status: waitingTask.status,
          progress: waitingTask.progress,
          note: approvalReason,
          data: {
            approvalState: waitingTask.approval.state,
            recoveryState: this.runtime.getRecoveryState(taskId),
          },
        });
        return;
      }

      const executingTask: DispatchTask = {
        ...planningTask,
        status: 'executing',
        progress: nextProgress,
        executingAt: nowIso(),
        taskIntent: plan.taskIntent,
        planSummary: buildReasoningPlanSummary(plan, classification.intent),
        progressDetail:
          nextProgress === 'researching'
            ? 'Researching with bounded retrieval.'
            : nextProgress === 'editing'
              ? 'Editing local files and artifacts.'
              : 'Executing bounded local task steps.',
        updatedAt: nowIso(),
        notes: [...planningTask.notes, 'Task is executing in the bounded local runtime.'],
        approval: {
          ...planningTask.approval,
          state: planningTask.approval.required ? planningTask.approval.state : 'none',
        },
        metadata: {
          ...planningTask.metadata,
          dispatchDecisionMode: decision.mode,
          dispatchDecisionReasoning: decision.reasoning,
          dispatchPolicy: policy,
          dispatchPlan: {
            taskIntent: plan.taskIntent,
            routingMode: plan.routingMode,
            reasoningDepth: plan.reasoningDepth,
            executionMode: plan.executionMode,
          },
        },
      };
      await this.store.write(executingTask);
      await this.runtime.writeRuntimeState(taskId, buildRuntimeState(executingTask, workspacePaths, this.runtime.getRecoveryState(taskId)));
      await this.runtime.recordLifecycleEvent(taskId, {
        kind: 'lifecycle',
        status: executingTask.status,
        progress: executingTask.progress,
        note: 'Task is executing in the bounded local runtime.',
        data: {
          recoveryState: this.runtime.getRecoveryState(taskId),
        },
      });

      if (executingTask.cancellationRequestedAt) {
        cleanupTerminalWorkspace = await this.failTask(executingTask, 'Task cancelled before execution began.', workspacePaths, {
          cleanupWorkspace: true,
          traceKind: 'lifecycle',
        });
        return;
      }

      const executionContext = this.runtime.createExecutionContext(taskId, policy.maxTimeMs);

      try {
        const response = await executeInteractionText({
          source: mapDispatchSourceToOperatorSource(executingTask.source),
          text: executingTask.text,
          mode: executingTask.mode,
          conversationId: executingTask.conversationId,
          messageId: executingTask.messageId,
          userId: executingTask.userId,
          displayName: executingTask.displayName,
          requestId: executingTask.id,
          runtimeContext: executionContext,
          signal: executionContext.signal,
          metadata: {
            dispatchTaskId: executingTask.id,
            dispatchSource: executingTask.source,
            dispatchRequestedArtifacts: JSON.stringify(executingTask.requestedArtifacts),
            dispatchTaskIntent: plan.taskIntent,
            dispatchMode: executingTask.mode,
            dispatchPlan: stringifyMetadataValue({
              taskIntent: plan.taskIntent,
              routingMode: plan.routingMode,
              reasoningDepth: plan.reasoningDepth,
              executionMode: plan.executionMode,
            }),
            dispatchPolicy: stringifyMetadataValue(policy),
            dispatchDecisionMode: decision.mode,
            dispatchDecisionReasoning: decision.reasoning.join(' | '),
            dispatchTaskMetadata: stringifyMetadataValue(normalizeStringMetadata(executingTask.metadata)),
          },
        });

        if ((await this.store.get(taskId))?.cancellationRequestedAt) {
          cleanupTerminalWorkspace = await this.failTask(executingTask, 'Task cancelled during execution.', workspacePaths, {
            cleanupWorkspace: true,
            traceKind: 'lifecycle',
          });
          return;
        }

        const operatorRun = response.runId ? await getOperatorRunStore().get(response.runId) : null;
        const modelProvider = resolveResponseModelProvider(response.modelId);
        const exportingAt = nowIso();
        const exportingTask: DispatchTask = {
          ...executingTask,
          status: 'exporting',
          progress: 'exporting',
          exportingAt,
          updatedAt: exportingAt,
          runId: response.runId ?? executingTask.runId,
          modelId: response.modelId,
          modelProvider,
          result: {
            text: response.text,
            sources: response.sources,
            runId: response.runId,
            modelId: response.modelId,
            modelProvider,
          },
          progressDetail: 'Exporting completed task artifacts.',
          notes: [...executingTask.notes, 'Execution completed. Exporting artifacts.'],
          metadata: {
            ...executingTask.metadata,
            dispatchResponse: {
              runId: response.runId,
              modelId: response.modelId,
              classification: response.classification,
              plan: {
                taskIntent: response.plan.taskIntent,
                routingMode: response.plan.routingMode,
                reasoningDepth: response.plan.reasoningDepth,
              },
            },
          },
        };
        await this.store.write(exportingTask);
        await this.runtime.writeRuntimeState(taskId, buildRuntimeState(exportingTask, workspacePaths, this.runtime.getRecoveryState(taskId)));
        await this.runtime.recordLifecycleEvent(taskId, {
          kind: 'lifecycle',
          status: exportingTask.status,
          progress: exportingTask.progress,
          note: 'Execution completed. Exporting artifacts.',
          data: {
            recoveryState: this.runtime.getRecoveryState(taskId),
          },
        });

        const workspaceArtifacts = await persistTaskWorkspaceArtifacts({
          task: exportingTask,
          response: {
            ...response,
            observabilityTrace: operatorRun?.artifacts
              .map((artifact) => artifact.metadata?.observabilityTrace)
              .find((candidate): candidate is RunTraceReport => Boolean(candidate && typeof candidate === 'object')),
          },
          operatorRun,
          requestedArtifacts: exportingTask.requestedArtifacts,
        });
        if (workspaceArtifacts.observabilityTrace) {
          await this.runtime.persistObservabilityTrace(taskId, workspaceArtifacts.observabilityTrace);
        }

        const completedTask: DispatchTask = {
          ...exportingTask,
          status: 'completed',
          progress: 'exporting',
          completedAt: nowIso(),
          updatedAt: nowIso(),
          artifacts: mergeArtifacts(exportingTask.artifacts, workspaceArtifacts.artifacts),
          notes: [...exportingTask.notes, 'Task completed and artifacts persisted.'],
        };
        await this.store.write(completedTask);
        await this.runtime.writeRuntimeState(taskId, buildRuntimeState(completedTask, workspacePaths, this.runtime.getRecoveryState(taskId)));
        await this.runtime.recordLifecycleEvent(taskId, {
          kind: 'lifecycle',
          status: completedTask.status,
          progress: completedTask.progress,
          note: 'Task completed and artifacts persisted.',
          data: {
            recoveryState: this.runtime.getRecoveryState(taskId),
          },
        });
      } catch (error) {
        const cancellationRequested = Boolean((await this.store.get(taskId))?.cancellationRequestedAt);
        const message = executionContext.signal.aborted
          ? 'Task cancelled during execution.'
          : error instanceof Error
            ? error.message
            : 'Dispatch execution failed.';
        cleanupTerminalWorkspace = await this.failTask(executingTask, message, workspacePaths, {
          cleanupWorkspace: cancellationRequested,
          traceKind: 'lifecycle',
        });
      } finally {
        this.runtime.releaseExecutionContext(taskId);
      }
    });

    if (cleanupTerminalWorkspace) {
      await this.runtime.cleanupTaskWorkspace(taskId).catch(() => undefined);
    }
  }

  private async failTask(
    task: DispatchTask,
    error: string,
    workspacePaths?: {
      root: string;
      browserSessionPath: string;
      runtimeTracePath: string;
      observabilityTracePath: string;
      approvalPath: string;
    },
    options?: {
      cleanupWorkspace?: boolean;
      traceKind?: 'lifecycle' | 'recovery';
    }
  ) {
    const now = nowIso();
    const failedTask: DispatchTask = {
      ...task,
      status: 'failed',
      progress: 'thinking',
      failedAt: now,
      updatedAt: now,
      error,
      notes: [...task.notes, error],
    };
    await this.store.write(failedTask);
    if (workspacePaths) {
      await this.runtime.recordLifecycleEvent(task.id, {
        kind: options?.traceKind ?? 'lifecycle',
        status: failedTask.status,
        progress: failedTask.progress,
        note: error,
        data: {
          cleanupWorkspace: options?.cleanupWorkspace ?? false,
          recoveryState: this.runtime.getRecoveryState(task.id),
        },
      });
      await this.runtime.writeRuntimeState(task.id, buildRuntimeState(failedTask, workspacePaths, this.runtime.getRecoveryState(task.id)));
    }
    return options?.cleanupWorkspace ?? false;
  }
}

let singletonDispatchService: DispatchService | null = null;

export function getDispatchService() {
  if (!singletonDispatchService) {
    singletonDispatchService = new DispatchService();
    void singletonDispatchService.bootstrap().catch((error) => {
      console.warn('Dispatch bootstrap failed', error);
    });
  }

  return singletonDispatchService;
}

export async function submitDispatchTask(request: DispatchTaskRequest, context: DispatchExecutionContext = {}) {
  return getDispatchService().submitTask(request, context);
}

export async function resumeDispatchTask(taskId: string, note?: string) {
  return getDispatchService().resumeTask(taskId, note);
}

export async function cancelDispatchTask(taskId: string, note?: string) {
  return getDispatchService().cancelTask(taskId, note);
}

export async function listDispatchTasks() {
  return getDispatchService().listTasks();
}

export async function getDispatchTask(taskId: string) {
  return getDispatchService().getTask(taskId);
}

export async function getDispatchStatus() {
  return getDispatchService().statusSnapshot();
}
