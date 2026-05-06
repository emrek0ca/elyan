import { mkdir, readdir, readFile, rename, writeFile } from 'fs/promises';
import path from 'path';
import { randomUUID } from 'crypto';
import { env } from '@/lib/env';
import {
  dispatchTaskSchema,
  type DispatchTask,
  type DispatchTaskRequest,
} from './types';

export interface DispatchTaskStore {
  create(task: DispatchTask): Promise<DispatchTask>;
  list(): Promise<DispatchTask[]>;
  get(taskId: string): Promise<DispatchTask | null>;
  write(task: DispatchTask): Promise<void>;
}

function defaultDispatchTasksDir() {
  return path.resolve(process.cwd(), env.ELYAN_STORAGE_DIR, 'dispatch-tasks');
}

function isMissingFileError(error: unknown) {
  return error instanceof Error && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT';
}

function parseDispatchTask(raw: string): DispatchTask {
  const data = JSON.parse(raw) as Record<string, unknown>;
  if (!data.version) {
    data.version = 1;
  }

  return dispatchTaskSchema.parse(data);
}

async function readDispatchTaskFile(filePath: string): Promise<DispatchTask> {
  const raw = await readFile(filePath, 'utf8');
  return parseDispatchTask(raw);
}

async function writeJsonAtomic(filePath: string, value: unknown) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const tempPath = `${filePath}.${process.pid}.${Date.now()}.${randomUUID().slice(0, 8)}.tmp`;
  await writeFile(tempPath, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(tempPath, filePath);
}

export class FileDispatchTaskStore implements DispatchTaskStore {
  constructor(private readonly tasksDir = defaultDispatchTasksDir()) {}

  async create(task: DispatchTask): Promise<DispatchTask> {
    await this.write(task);
    return task;
  }

  async list(): Promise<DispatchTask[]> {
    let entries: string[];

    try {
      entries = await readdir(this.tasksDir);
    } catch (error) {
      if (isMissingFileError(error)) {
        return [];
      }

      throw error;
    }

    const tasks = await Promise.all(
      entries
        .filter((entry) => entry.endsWith('.json'))
        .map(async (entry) => {
          const task = await readDispatchTaskFile(path.join(this.tasksDir, entry));
          return task;
        })
    );

    return tasks.sort((left, right) => right.createdAt.localeCompare(left.createdAt));
  }

  async get(taskId: string): Promise<DispatchTask | null> {
    try {
      return await readDispatchTaskFile(this.taskPath(taskId));
    } catch (error) {
      if (isMissingFileError(error)) {
        return null;
      }

      throw error;
    }
  }

  async write(task: DispatchTask): Promise<void> {
    const parsed = dispatchTaskSchema.parse(task);
    const filePath = this.taskPath(parsed.id);
    await writeJsonAtomic(filePath, parsed);
  }

  private taskPath(taskId: string) {
    return path.join(this.tasksDir, `${taskId}.json`);
  }
}

let singletonStore: FileDispatchTaskStore | null = null;

export function getDispatchTaskStore() {
  if (!singletonStore) {
    singletonStore = new FileDispatchTaskStore();
  }

  return singletonStore;
}

export function buildDispatchTaskId() {
  return `dispatch_${Date.now()}_${randomUUID().slice(0, 8)}`;
}

export function createDispatchTaskRecord(input: {
  id: string;
  source: DispatchTask['source'];
  title: string;
  objective: string;
  text: string;
  mode: DispatchTask['mode'];
  autoStart: boolean;
  accountId?: string;
  spaceId?: string;
  conversationId?: string;
  messageId?: string;
  userId?: string;
  displayName?: string;
  requestedArtifacts?: DispatchTask['requestedArtifacts'];
  metadata?: Record<string, unknown>;
}): DispatchTask {
  const createdAt = new Date().toISOString();
  return dispatchTaskSchema.parse({
    id: input.id,
    version: 1,
    source: input.source,
    title: input.title,
    objective: input.objective,
    text: input.text,
    status: 'queued',
    progress: 'thinking',
    createdAt,
    updatedAt: createdAt,
    queuedAt: createdAt,
    autoStart: input.autoStart,
    accountId: input.accountId,
    spaceId: input.spaceId,
    conversationId: input.conversationId,
    messageId: input.messageId,
    userId: input.userId,
    displayName: input.displayName,
    mode: input.mode,
    requestedArtifacts: input.requestedArtifacts ?? [],
    artifacts: [],
    notes: ['Task received and queued for bounded remote execution.'],
    metadata: input.metadata ?? {},
  });
}

export function normalizeDispatchTaskRequest(
  request: DispatchTaskRequest
): Pick<
  DispatchTask,
  'title' | 'objective' | 'text' | 'source' | 'mode' | 'autoStart' | 'conversationId' | 'messageId' | 'userId' | 'displayName' | 'requestedArtifacts' | 'metadata'
> {
  const title = request.title?.trim() || request.text.trim().slice(0, 80) || 'Remote task';
  return {
    title,
    objective: title,
    text: request.text.trim(),
    source: request.source,
    mode: request.mode,
    autoStart: request.autoStart,
    conversationId: request.conversationId,
    messageId: request.messageId,
    userId: request.userId,
    displayName: request.displayName,
    requestedArtifacts: request.requestedArtifacts,
    metadata: request.metadata,
  };
}

