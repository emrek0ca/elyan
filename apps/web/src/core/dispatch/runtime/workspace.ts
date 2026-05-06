import { appendFile, mkdir, readFile, rename, writeFile } from 'fs/promises';
import path from 'path';
import lockfile from 'proper-lockfile';
import { randomUUID } from 'crypto';
import { env } from '@/lib/env';

export type TaskWorkspacePaths = {
  taskId: string;
  root: string;
  artifactsDir: string;
  browserDir: string;
  checkpointsDir: string;
  tracesDir: string;
  manifestPath: string;
  statePath: string;
  runtimeTracePath: string;
  observabilityTracePath: string;
  approvalPath: string;
  browserSessionPath: string;
};

export type TaskRuntimeState = {
  taskId: string;
  workspacePath: string;
  status: string;
  progress: string;
  updatedAt: string;
  checkpoint?: string;
  approvalState?: string;
  recoveryState?: 'fresh' | 'resumed' | 'recovered';
  browserSessionPath?: string;
  tracePath?: string;
  observabilityTracePath?: string;
  notes?: string[];
  metadata?: Record<string, unknown>;
};

export type RuntimeTraceEvent = {
  timestamp: string;
  kind: 'lifecycle' | 'checkpoint' | 'artifact' | 'observability' | 'browser' | 'recovery';
  taskId: string;
  status?: string;
  progress?: string;
  note?: string;
  data?: Record<string, unknown>;
};

export function resolveTaskWorkspacePaths(taskId: string): TaskWorkspacePaths {
  const root = path.resolve(process.cwd(), env.ELYAN_STORAGE_DIR, 'tasks', taskId);
  return {
    taskId,
    root,
    artifactsDir: path.join(root, 'artifacts'),
    browserDir: path.join(root, 'browser'),
    checkpointsDir: path.join(root, 'checkpoints'),
    tracesDir: path.join(root, 'traces'),
    manifestPath: path.join(root, 'manifest.json'),
    statePath: path.join(root, 'state.json'),
    runtimeTracePath: path.join(root, 'traces', 'runtime-trace.jsonl'),
    observabilityTracePath: path.join(root, 'traces', 'observability.json'),
    approvalPath: path.join(root, 'checkpoints', 'approval.json'),
    browserSessionPath: path.join(root, 'browser', 'storage-state.json'),
  };
}

export async function ensureTaskWorkspace(paths: TaskWorkspacePaths) {
  await Promise.all([
    mkdir(paths.root, { recursive: true }),
    mkdir(paths.artifactsDir, { recursive: true }),
    mkdir(paths.browserDir, { recursive: true }),
    mkdir(paths.checkpointsDir, { recursive: true }),
    mkdir(paths.tracesDir, { recursive: true }),
  ]);
}

export async function writeJsonAtomic(filePath: string, value: unknown) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.${randomUUID().slice(0, 8)}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(tempPath, filePath);
}

export async function readJsonFile<T>(filePath: string): Promise<T | null> {
  try {
    const raw = await readFile(filePath, 'utf8');
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function isPathInsideWorkspace(candidatePath: string, workspaceRoot: string) {
  const relative = path.relative(workspaceRoot, candidatePath);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

export type TaskWorkspaceRecoverySnapshot = {
  state: TaskRuntimeState | null;
  approval: Record<string, unknown> | null;
  manifest: Record<string, unknown> | null;
  runtimeTrace: unknown | null;
  observabilityTrace: unknown | null;
};

export async function readTaskWorkspaceRecoverySnapshot(paths: TaskWorkspacePaths): Promise<TaskWorkspaceRecoverySnapshot> {
  const [state, approval, manifest, runtimeTrace, observabilityTrace] = await Promise.all([
    readJsonFile<TaskRuntimeState>(paths.statePath),
    readJsonFile<Record<string, unknown>>(paths.approvalPath),
    readJsonFile<Record<string, unknown>>(paths.manifestPath),
    readJsonFile(paths.runtimeTracePath),
    readJsonFile(paths.observabilityTracePath),
  ]);

  return {
    state,
    approval,
    manifest,
    runtimeTrace,
    observabilityTrace,
  };
}

export async function appendJsonLine(filePath: string, value: unknown) {
  await mkdir(path.dirname(filePath), { recursive: true });
  await appendFile(filePath, `${JSON.stringify(value)}\n`, 'utf8');
}

export async function withTaskWorkspaceLock<T>(workspacePath: string, run: () => Promise<T>) {
  await mkdir(workspacePath, { recursive: true });
  const release = await lockfile.lock(workspacePath, {
    realpath: false,
    retries: {
      retries: 8,
      factor: 1.4,
      minTimeout: 40,
      maxTimeout: 250,
    },
  });

  try {
    return await run();
  } finally {
    await release();
  }
}
