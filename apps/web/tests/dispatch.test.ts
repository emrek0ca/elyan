import { access, mkdir, mkdtemp, readFile, rm, writeFile } from 'fs/promises';
import os from 'os';
import path from 'path';
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import type { DispatchTask } from '@/core/dispatch';

const executeInteractionTextMock = vi.fn();
const resolveModelMock = vi.fn(() => ({
  provider: { id: 'ollama' },
}));
const buildExecutionSurfaceSnapshotMock = vi.fn(() => ({
  local: {
    capabilities: [],
    bridgeTools: [],
  },
  mcp: {
    servers: [],
    tools: [],
    resources: [],
    resourceTemplates: [],
    prompts: [],
  },
}));
const buildOrchestrationPlanMock = vi.fn((query: string) => makePlan(query));
const decideExecutionMock = vi.fn(async ({ query }: { query: string }) => makeDecision(query));
const decidePolicyMock = vi.fn(() => ({
  maxSteps: 3,
  maxRetries: 1,
  maxTimeMs: 10_000,
  maxCostUsd: 1,
  maxTokens: 1_000,
  allowedTools: ['local_tools'],
}));
const classifyInteractionIntentMock = vi.fn((query: string) => ({
  intent: /research/i.test(query) ? 'research' : 'direct_answer',
  resolvedMode: /research/i.test(query) ? 'research' : 'speed',
  confidence: 'high',
  notes: [],
}));
const getOperatorRunMock = vi.fn(async () => null);

vi.mock('@/core/interaction/orchestrator', () => ({
  executeInteractionText: executeInteractionTextMock,
}));

vi.mock('@/core/orchestration', () => ({
  buildExecutionSurfaceSnapshot: buildExecutionSurfaceSnapshotMock,
  buildOrchestrationPlan: buildOrchestrationPlanMock,
}));

vi.mock('@/core/decision/engine', () => ({
  decideExecution: decideExecutionMock,
}));

vi.mock('@/core/control/policy-engine', () => ({
  decidePolicy: decidePolicyMock,
}));

vi.mock('@/core/interaction/intent', () => ({
  classifyInteractionIntent: classifyInteractionIntentMock,
}));

vi.mock('@/core/operator', () => ({
  getOperatorRunStore: vi.fn(() => ({
    get: getOperatorRunMock,
  })),
}));

vi.mock('@/core/providers', () => ({
  registry: {
    resolveModel: resolveModelMock,
  },
}));

function makePlan(query: string) {
  const requiresConfirmation = /delete|approve|approval|danger/i.test(query);
  return {
    taskIntent: 'procedural',
    executionMode: 'single',
    routingMode: 'local_first',
    reasoningDepth: 'standard',
    teamPolicy: {
      enabledByDefault: false,
      modelRoutingMode: 'local_only',
      requiredRoles: [],
    },
    executionPolicy: {
      shouldRetrieve: false,
      notes: [],
      primary: { kind: 'direct_answer' },
      candidates: [],
      requiresConfirmation,
      fallbackReason: requiresConfirmation ? 'Approval required before execution can continue.' : undefined,
    },
    retrieval: {
      rounds: 0,
      maxUrls: 0,
      rerankTopK: 0,
      language: 'tr',
      expandSearchQueries: false,
    },
    usageBudget: {
      inference: 0,
      retrieval: 0,
      integrations: 0,
      evaluation: 0,
    },
    surface: buildExecutionSurfaceSnapshotMock(),
    searchRounds: 0,
  } as const;
}

function makeDecision(query: string) {
  const isResearch = /research/i.test(query);

  return {
    mode: isResearch ? 'research' : 'fast',
    modelId: 'local:model-a',
    modelPerformance: 0.9,
    tools: {
      allowWebSearch: isResearch,
      allowConnectors: false,
      allowLocalTools: true,
      allowBrowser: false,
      preferredTools: ['local_tools'],
    },
    steps: {
      complexity: 'low',
      stepBudget: 1,
      retryLimit: 0,
    },
    reasoning: ['deterministic test decision'],
    artifactCount: 0,
  } as const;
}

async function loadDispatchModule() {
  vi.resetModules();
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), 'elyan-dispatch-'));
  process.env.DATABASE_URL = 'https://example.com';
  process.env.ELYAN_STORAGE_DIR = tmpDir;

  const mod = await import('@/core/dispatch');

  return {
    tmpDir,
    mod,
  };
}

async function loadDispatchModuleWithSeededTask(task: DispatchTask) {
  vi.resetModules();
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), 'elyan-dispatch-'));
  process.env.DATABASE_URL = 'https://example.com';
  process.env.ELYAN_STORAGE_DIR = tmpDir;
  const tasksDir = path.join(tmpDir, 'dispatch-tasks');
  await mkdir(tasksDir, { recursive: true });
  await writeFile(path.join(tasksDir, `${task.id}.json`), `${JSON.stringify(task, null, 2)}\n`, 'utf8');

  const mod = await import('@/core/dispatch');

  return {
    tmpDir,
    mod,
  };
}

async function pathExists(filePath: string) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

async function waitForTask(
  getDispatchTask: (taskId: string) => Promise<DispatchTask | null>,
  taskId: string,
  expectedStatus: DispatchTask['status'],
  timeoutMs = 3000
) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const task = await getDispatchTask(taskId);
    if (task?.status === expectedStatus) {
      return task;
    }

    await new Promise((resolve) => setTimeout(resolve, 20));
  }

  throw new Error(`Timed out waiting for task ${taskId} to reach ${expectedStatus}`);
}

describe('dispatch service', () => {
  let tmpDir = '';

  beforeEach(() => {
    executeInteractionTextMock.mockReset();
    resolveModelMock.mockClear();
    buildExecutionSurfaceSnapshotMock.mockClear();
    buildOrchestrationPlanMock.mockClear();
    decideExecutionMock.mockClear();
    decidePolicyMock.mockClear();
    classifyInteractionIntentMock.mockClear();
    getOperatorRunMock.mockClear();
  });

  afterEach(async () => {
    if (tmpDir) {
      await rm(tmpDir, { recursive: true, force: true });
      tmpDir = '';
    }
  });

  it('queues a task without auto-starting when autoStart is false', async () => {
    const loaded = await loadDispatchModule();
    tmpDir = loaded.tmpDir;
    const { submitDispatchTask, getDispatchTask, getDispatchStatus } = loaded.mod;

    const task = await submitDispatchTask({
      text: 'Draft a short project update',
      source: 'api',
      autoStart: false,
      mode: 'speed',
      requestedArtifacts: ['markdown'],
      metadata: {},
    });

    const stored = await getDispatchTask(task.id);
    expect(stored?.status).toBe('queued');
    expect(stored?.progress).toBe('thinking');

    const snapshot = await getDispatchStatus();
    expect(snapshot.tasks.queued).toBe(1);
    expect(snapshot.tasks.total).toBe(1);
    expect(snapshot.tasks.latest?.id).toBe(task.id);
    expect(executeInteractionTextMock).not.toHaveBeenCalled();
  });

  it('auto-starts bounded work and persists the result artifacts', async () => {
    const loaded = await loadDispatchModule();
    tmpDir = loaded.tmpDir;
    const { submitDispatchTask, getDispatchTask } = loaded.mod;

    executeInteractionTextMock.mockResolvedValue({
      text: 'Completed dispatch task',
      sources: [{ url: 'local://result', title: 'Local result' }],
      plan: makePlan('Summarize this document'),
      surface: buildExecutionSurfaceSnapshotMock(),
      modelId: 'local:model-a',
      classification: {
        intent: 'direct_answer',
        resolvedMode: 'speed',
        confidence: 'high',
        notes: [],
      },
      runId: 'run_dispatch_1',
    });

    const task = await submitDispatchTask({
      text: 'Summarize this document',
      source: 'api',
      autoStart: true,
      mode: 'speed',
      requestedArtifacts: ['markdown'],
      metadata: {},
    });

    const completed = await waitForTask(getDispatchTask, task.id, 'completed');
    expect(completed?.result?.text).toBe('Completed dispatch task');
    expect(completed?.runId).toBe('run_dispatch_1');
    expect(completed?.modelId).toBe('local:model-a');
    expect(completed?.modelProvider).toBe('ollama');
    expect(completed?.artifacts.length).toBeGreaterThanOrEqual(2);
    expect(executeInteractionTextMock).toHaveBeenCalledTimes(1);
    expect(executeInteractionTextMock.mock.calls[0]?.[0]?.runtimeContext?.workspacePath).toContain(
      path.join(tmpDir, 'tasks', task.id)
    );
    expect(executeInteractionTextMock).toHaveBeenCalledWith(
      expect.objectContaining({
        text: 'Summarize this document',
        requestId: task.id,
        source: 'web',
      })
    );
    expect(
      completed?.artifacts.every((artifact) => artifact.filePath.startsWith(path.join(tmpDir, 'tasks', task.id)))
    ).toBe(true);
    const summaryArtifact = completed?.artifacts.find((artifact) => artifact.title === 'Task summary');
    expect(summaryArtifact?.filePath).toBeTruthy();
    if (summaryArtifact?.filePath) {
      const summary = await readFile(summaryArtifact.filePath, 'utf8');
      expect(summary).toContain('Completed dispatch task');
    }
  });

  it('pauses for approval and resumes safely', async () => {
    const loaded = await loadDispatchModule();
    tmpDir = loaded.tmpDir;
    const { submitDispatchTask, getDispatchTask, resumeDispatchTask } = loaded.mod;

    const waitingTask = await submitDispatchTask({
      text: 'Delete the temporary file after approval',
      source: 'api',
      autoStart: true,
      mode: 'speed',
      requestedArtifacts: ['markdown'],
      metadata: {},
    });

    const paused = await waitForTask(getDispatchTask, waitingTask.id, 'waiting_approval');
    expect(paused?.approval.required).toBe(true);
    expect(executeInteractionTextMock).not.toHaveBeenCalled();

    executeInteractionTextMock.mockResolvedValueOnce({
      text: 'Approval completed',
      sources: [{ url: 'local://result', title: 'Local result' }],
      plan: makePlan('Delete the temporary file after approval'),
      surface: buildExecutionSurfaceSnapshotMock(),
      modelId: 'local:model-a',
      classification: {
        intent: 'direct_answer',
        resolvedMode: 'speed',
        confidence: 'high',
        notes: [],
      },
      runId: 'run_dispatch_approval_1',
    });

    await resumeDispatchTask(waitingTask.id, 'Approved by operator.');
    const completed = await waitForTask(getDispatchTask, waitingTask.id, 'completed');
    expect(completed?.result?.text).toBe('Approval completed');
    expect(executeInteractionTextMock).toHaveBeenCalledTimes(1);
  });

  it('can cancel a queued task before it starts', async () => {
    const loaded = await loadDispatchModule();
    tmpDir = loaded.tmpDir;
    const { submitDispatchTask, getDispatchTask, cancelDispatchTask } = loaded.mod;

    const task = await submitDispatchTask({
      text: 'Write a report later',
      source: 'api',
      autoStart: false,
      mode: 'speed',
      requestedArtifacts: ['markdown'],
      metadata: {},
    });

    const cancelled = await cancelDispatchTask(task.id, 'No longer needed.');
    expect(cancelled?.status).toBe('failed');
    expect(cancelled?.error).toContain('No longer needed');

    const stored = await getDispatchTask(task.id);
    expect(stored?.status).toBe('failed');
    expect(await pathExists(path.join(tmpDir, 'tasks', task.id))).toBe(false);
    expect(executeInteractionTextMock).not.toHaveBeenCalled();
  });

  it('pauses for approval and resumes after approval is granted', async () => {
    const loaded = await loadDispatchModule();
    tmpDir = loaded.tmpDir;
    const { submitDispatchTask, getDispatchTask, resumeDispatchTask } = loaded.mod;

    executeInteractionTextMock.mockResolvedValue({
      text: 'Approval-gated task completed',
      sources: [],
      plan: makePlan('Approved task can continue'),
      surface: buildExecutionSurfaceSnapshotMock(),
      modelId: 'local:model-a',
      classification: {
        intent: 'direct_answer',
        resolvedMode: 'speed',
        confidence: 'high',
        notes: [],
      },
      runId: 'run_dispatch_approval',
    });

    const task = await submitDispatchTask({
      text: 'Please delete the old draft',
      source: 'api',
      autoStart: true,
      mode: 'speed',
      requestedArtifacts: [],
      metadata: {},
    });

    const waiting = await waitForTask(getDispatchTask, task.id, 'waiting_approval');
    expect(waiting?.approval.required).toBe(true);
    expect(waiting?.approval.state).toBe('pending');
    expect(executeInteractionTextMock).not.toHaveBeenCalled();

    await resumeDispatchTask(task.id, 'approval granted');
    const completed = await waitForTask(getDispatchTask, task.id, 'completed');
    expect(completed?.approval.state).toBe('approved');
    expect(completed?.notes.some((note) => note.includes('approval granted'))).toBe(true);
    expect(executeInteractionTextMock).toHaveBeenCalledTimes(1);
  });

  it('cancels queued work without starting execution', async () => {
    const loaded = await loadDispatchModule();
    tmpDir = loaded.tmpDir;
    const { submitDispatchTask, cancelDispatchTask, getDispatchTask } = loaded.mod;

    const task = await submitDispatchTask({
      text: 'Write a long report',
      source: 'api',
      autoStart: false,
      mode: 'speed',
      requestedArtifacts: [],
      metadata: {},
    });

    const cancelled = await cancelDispatchTask(task.id, 'no longer needed');
    expect(cancelled?.status).toBe('failed');
    expect(cancelled?.error).toContain('no longer needed');
    expect(cancelled?.cancellationRequestedAt).toBeDefined();
    expect(await getDispatchTask(task.id)).toMatchObject({
      status: 'failed',
    });
    expect(executeInteractionTextMock).not.toHaveBeenCalled();
  });

  it('fails closed on recovered executing tasks to avoid duplicate side effects', async () => {
    const task = {
      id: 'dispatch_recovered_executing',
      version: 1,
      source: 'api',
      title: 'Recovered execution',
      objective: 'Recovered execution',
      text: 'Write a file',
      status: 'executing',
      progress: 'editing',
      createdAt: '2026-05-06T00:00:00.000Z',
      updatedAt: '2026-05-06T00:00:30.000Z',
      executingAt: '2026-05-06T00:00:30.000Z',
      autoStart: true,
      mode: 'speed',
      approval: { state: 'none', required: false },
      artifacts: [],
      requestedArtifacts: ['markdown'],
      notes: [],
      metadata: {},
    } as DispatchTask;
    const loaded = await loadDispatchModuleWithSeededTask(task);
    tmpDir = loaded.tmpDir;
    const { getDispatchTask } = loaded.mod;
    const { getDispatchRuntimeCoordinator } = await import('@/core/dispatch/runtime');
    const runtime = getDispatchRuntimeCoordinator();
    const lifecycleSpy = vi.spyOn(runtime, 'recordLifecycleEvent');

    const failed = await waitForTask(getDispatchTask, task.id, 'failed');

    expect(failed?.error).toContain('failing closed');
    expect(await pathExists(path.join(tmpDir, 'tasks', task.id))).toBe(false);
    expect(
      lifecycleSpy.mock.calls.some(
        ([eventTaskId, event]) =>
          eventTaskId === task.id &&
          event.kind === 'recovery' &&
          event.status === 'failed' &&
          typeof event.note === 'string' &&
          event.note.includes('Recovered task was executing')
      )
    ).toBe(true);
    expect(executeInteractionTextMock).not.toHaveBeenCalled();
  });

  it('fails closed on recovered exporting tasks without replaying execution', async () => {
    const task = {
      id: 'dispatch_recovered_exporting',
      version: 1,
      source: 'api',
      title: 'Recovered export',
      objective: 'Recovered export',
      text: 'Summarize after restart',
      status: 'exporting',
      progress: 'exporting',
      createdAt: '2026-05-06T00:00:00.000Z',
      updatedAt: '2026-05-06T00:01:00.000Z',
      exportingAt: '2026-05-06T00:01:00.000Z',
      autoStart: true,
      mode: 'speed',
      runId: 'run_recovered_export',
      modelId: 'local:model-a',
      modelProvider: 'ollama',
      approval: { state: 'none', required: false },
      result: {
        text: 'Recovered result body',
        sources: [{ url: 'local://recovered', title: 'Recovered source' }],
        runId: 'run_recovered_export',
        modelId: 'local:model-a',
        modelProvider: 'ollama',
      },
      artifacts: [],
      requestedArtifacts: ['markdown'],
      notes: [],
      metadata: {
        dispatchResponse: {
          classification: { intent: 'direct_answer', confidence: 'high' },
          plan: { taskIntent: 'procedural', routingMode: 'local_first', reasoningDepth: 'standard' },
        },
      },
    } as DispatchTask;
    const loaded = await loadDispatchModuleWithSeededTask(task);
    tmpDir = loaded.tmpDir;
    const { getDispatchTask } = loaded.mod;
    const { getDispatchRuntimeCoordinator } = await import('@/core/dispatch/runtime');
    const runtime = getDispatchRuntimeCoordinator();
    const lifecycleSpy = vi.spyOn(runtime, 'recordLifecycleEvent');

    const failed = await waitForTask(getDispatchTask, task.id, 'failed');

    expect(failed?.error).toContain('failing closed');
    expect(await pathExists(path.join(tmpDir, 'tasks', task.id))).toBe(false);
    expect(
      lifecycleSpy.mock.calls.some(
        ([eventTaskId, event]) =>
          eventTaskId === task.id &&
          event.kind === 'recovery' &&
          event.status === 'failed' &&
          typeof event.note === 'string' &&
          event.note.includes('Recovered task was exporting')
      )
    ).toBe(true);
    expect(executeInteractionTextMock).not.toHaveBeenCalled();
  });

  it('builds a live status snapshot from task states', async () => {
    const tasks: DispatchTask[] = [
      {
        id: 'task_completed',
        version: 1,
        source: 'api',
        title: 'Completed task',
        objective: 'Completed task',
        text: 'done',
        status: 'completed',
        progress: 'exporting',
        createdAt: '2026-05-06T00:00:00.000Z',
        updatedAt: '2026-05-06T00:01:00.000Z',
        completedAt: '2026-05-06T00:01:00.000Z',
        autoStart: true,
        mode: 'speed',
        approval: { state: 'none', required: false },
        artifacts: [],
        requestedArtifacts: [],
        notes: [],
        metadata: {},
      } as DispatchTask,
      {
        id: 'task_queued',
        version: 1,
        source: 'api',
        title: 'Queued task',
        objective: 'Queued task',
        text: 'queued',
        status: 'queued',
        progress: 'thinking',
        createdAt: '2026-05-06T00:02:00.000Z',
        updatedAt: '2026-05-06T00:02:00.000Z',
        queuedAt: '2026-05-06T00:02:00.000Z',
        autoStart: true,
        mode: 'speed',
        approval: { state: 'none', required: false },
        artifacts: [],
        requestedArtifacts: [],
        notes: [],
        metadata: {},
      } as DispatchTask,
      {
        id: 'task_waiting',
        version: 1,
        source: 'api',
        title: 'Waiting task',
        objective: 'Waiting task',
        text: 'waiting',
        status: 'waiting_approval',
        progress: 'thinking',
        createdAt: '2026-05-06T00:03:00.000Z',
        updatedAt: '2026-05-06T00:03:00.000Z',
        waitingApprovalAt: '2026-05-06T00:03:00.000Z',
        autoStart: true,
        mode: 'speed',
        approval: { state: 'pending', required: true, reason: 'approval needed', requestedAt: '2026-05-06T00:03:00.000Z' },
        artifacts: [],
        requestedArtifacts: [],
        notes: [],
        metadata: {},
      } as DispatchTask,
      {
        id: 'task_failed',
        version: 1,
        source: 'api',
        title: 'Failed task',
        objective: 'Failed task',
        text: 'failed',
        status: 'failed',
        progress: 'thinking',
        createdAt: '2026-05-06T00:04:00.000Z',
        updatedAt: '2026-05-06T00:04:00.000Z',
        failedAt: '2026-05-06T00:04:00.000Z',
        autoStart: true,
        mode: 'speed',
        approval: { state: 'none', required: false },
        artifacts: [],
        requestedArtifacts: [],
        notes: [],
        metadata: {},
      } as DispatchTask,
    ];

    const { buildDispatchStatusSnapshot } = await import('@/core/dispatch/status');
    const snapshot = buildDispatchStatusSnapshot(tasks);

    expect(snapshot.tasks.total).toBe(4);
    expect(snapshot.tasks.queued).toBe(1);
    expect(snapshot.tasks.waitingApproval).toBe(1);
    expect(snapshot.tasks.completed).toBe(1);
    expect(snapshot.tasks.failed).toBe(1);
    expect(snapshot.status).toBe('degraded');
  });
});
