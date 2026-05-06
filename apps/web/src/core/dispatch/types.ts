import { z } from 'zod';
import type { OperatorSource } from '@/core/operator';

export const dispatchTaskSourceSchema = z.enum([
  'phone',
  'web',
  'desktop',
  'api',
  'telegram',
  'whatsapp_cloud',
  'whatsapp_baileys',
  'imessage_bluebubbles',
  'voice',
  'cli',
]);

export const dispatchTaskStatusSchema = z.enum([
  'queued',
  'planning',
  'executing',
  'waiting_approval',
  'exporting',
  'completed',
  'failed',
]);

export const dispatchTaskProgressSchema = z.enum([
  'thinking',
  'researching',
  'executing',
  'editing',
  'exporting',
]);

export const dispatchArtifactKindSchema = z.enum([
  'pdf',
  'pptx',
  'markdown',
  'spreadsheet',
  'code_file',
]);

export const dispatchTaskRequestSchema = z.object({
  text: z.string().trim().min(1),
  title: z.string().trim().min(1).optional(),
  source: dispatchTaskSourceSchema.default('api'),
  mode: z.enum(['speed', 'research']).default('speed'),
  conversationId: z.string().trim().min(1).optional(),
  messageId: z.string().trim().min(1).optional(),
  userId: z.string().trim().min(1).optional(),
  displayName: z.string().trim().min(1).optional(),
  metadata: z.record(z.string(), z.unknown()).default({}),
  requestedArtifacts: z.array(dispatchArtifactKindSchema).default([]),
  autoStart: z.boolean().default(true),
});

export const dispatchTaskArtifactSchema = z.object({
  id: z.string().min(1),
  kind: dispatchArtifactKindSchema,
  title: z.string().min(1),
  filePath: z.string().min(1),
  mimeType: z.string().min(1),
  sizeBytes: z.number().int().nonnegative(),
  createdAt: z.string().datetime(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const dispatchTaskApprovalSchema = z.object({
  state: z.enum(['none', 'pending', 'approved', 'rejected']).default('none'),
  required: z.boolean().default(false),
  reason: z.string().min(1).optional(),
  requestedAt: z.string().datetime().optional(),
  resolvedAt: z.string().datetime().optional(),
  resolvedBy: z.string().min(1).optional(),
});

export const dispatchTaskResultSchema = z.object({
  text: z.string().default(''),
  sources: z
    .array(
      z.object({
        url: z.string().min(1),
        title: z.string().min(1),
      })
    )
    .default([]),
  runId: z.string().min(1).optional(),
  modelId: z.string().min(1).optional(),
  modelProvider: z.string().min(1).optional(),
});

export const dispatchTaskSchema = z.object({
  id: z.string().min(1),
  version: z.literal(1),
  source: dispatchTaskSourceSchema,
  title: z.string().min(1),
  objective: z.string().min(1),
  text: z.string().min(1),
  status: dispatchTaskStatusSchema,
  progress: dispatchTaskProgressSchema,
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  queuedAt: z.string().datetime().optional(),
  planningAt: z.string().datetime().optional(),
  executingAt: z.string().datetime().optional(),
  waitingApprovalAt: z.string().datetime().optional(),
  exportingAt: z.string().datetime().optional(),
  completedAt: z.string().datetime().optional(),
  failedAt: z.string().datetime().optional(),
  cancellationRequestedAt: z.string().datetime().optional(),
  cancelledAt: z.string().datetime().optional(),
  autoStart: z.boolean().default(true),
  accountId: z.string().min(1).optional(),
  spaceId: z.string().min(1).optional(),
  conversationId: z.string().min(1).optional(),
  messageId: z.string().min(1).optional(),
  userId: z.string().min(1).optional(),
  displayName: z.string().min(1).optional(),
  mode: z.enum(['speed', 'research']).default('speed'),
  runId: z.string().min(1).optional(),
  modelId: z.string().min(1).optional(),
  modelProvider: z.string().min(1).optional(),
  taskIntent: z.string().min(1).optional(),
  planSummary: z.string().min(1).optional(),
  progressDetail: z.string().min(1).optional(),
  approval: dispatchTaskApprovalSchema.default({ state: 'none', required: false }),
  result: dispatchTaskResultSchema.optional(),
  artifacts: z.array(dispatchTaskArtifactSchema).default([]),
  requestedArtifacts: z.array(dispatchArtifactKindSchema).default([]),
  notes: z.array(z.string().min(1)).default([]),
  error: z.string().min(1).optional(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const dispatchTaskUpdateSchema = dispatchTaskSchema.partial().extend({
  id: z.string().min(1).optional(),
});

export type DispatchTaskSource = z.infer<typeof dispatchTaskSourceSchema>;
export type DispatchTaskStatus = z.infer<typeof dispatchTaskStatusSchema>;
export type DispatchTaskProgress = z.infer<typeof dispatchTaskProgressSchema>;
export type DispatchArtifactKind = z.infer<typeof dispatchArtifactKindSchema>;
export type DispatchTaskRequest = z.infer<typeof dispatchTaskRequestSchema>;
export type DispatchTaskArtifact = z.infer<typeof dispatchTaskArtifactSchema>;
export type DispatchTaskApproval = z.infer<typeof dispatchTaskApprovalSchema>;
export type DispatchTaskResult = z.infer<typeof dispatchTaskResultSchema>;
export type DispatchTask = z.infer<typeof dispatchTaskSchema>;

export type DispatchTaskSummary = {
  id: string;
  title: string;
  status: DispatchTaskStatus;
  progress: DispatchTaskProgress;
  createdAt: string;
  updatedAt: string;
  runId?: string;
  modelId?: string;
  approvalRequired: boolean;
  artifactCount: number;
  noteCount: number;
  source: DispatchTaskSource;
};

export type DispatchStatusSnapshot = {
  status: 'healthy' | 'degraded' | 'unknown';
  summary: string;
  tasks: {
    total: number;
    queued: number;
    planning: number;
    executing: number;
    waitingApproval: number;
    exporting: number;
    completed: number;
    failed: number;
    latest?: DispatchTaskSummary;
  };
};

export type DispatchExecutionContext = {
  accountId?: string;
  spaceId?: string;
  controlPlaneSession?: {
    accountId?: string | null;
    deviceId?: string | null;
    token?: string | null;
  } | null;
};

export type DispatchExecutionResult = {
  task: DispatchTask;
  response: {
    text: string;
    sources: Array<{ url: string; title: string }>;
    plan: {
      taskIntent: string;
      routingMode: string;
      reasoningDepth: string;
    };
    surface: {
      local: {
        capabilities: Array<{ id: string; title: string; description: string; enabled: boolean }>;
        bridgeTools: Array<{ id: string; title: string; description: string; enabled: boolean }>;
      };
      mcp: {
        servers: Array<{ id: string; title: string; description: string; enabled: boolean }>;
        tools: Array<{ id: string; title: string; description: string; enabled: boolean }>;
        resources: Array<{ name: string; uri: string; title: string; description: string; enabled: boolean }>;
        resourceTemplates: Array<{ name: string; uriTemplate: string; title: string; description: string; enabled: boolean }>;
        prompts: Array<{ name: string; title: string; description: string; enabled: boolean }>;
      };
    };
    modelId: string;
    classification: {
      intent: string;
      confidence: string;
    };
    runId?: string;
  };
};

export function mapDispatchSourceToOperatorSource(source: DispatchTaskSource): OperatorSource {
  switch (source) {
    case 'telegram':
      return 'telegram';
    case 'whatsapp_cloud':
      return 'whatsapp_cloud';
    case 'whatsapp_baileys':
      return 'whatsapp_baileys';
    case 'imessage_bluebubbles':
      return 'imessage_bluebubbles';
    case 'voice':
      return 'voice';
    case 'cli':
      return 'cli';
    case 'desktop':
      return 'cli';
    case 'phone':
    case 'api':
    case 'web':
    default:
      return 'web';
  }
}

export function summarizeDispatchTask(task: DispatchTask): DispatchTaskSummary {
  return {
    id: task.id,
    title: task.title,
    status: task.status,
    progress: task.progress,
    createdAt: task.createdAt,
    updatedAt: task.updatedAt,
    runId: task.runId,
    modelId: task.modelId,
    approvalRequired: task.approval.required,
    artifactCount: task.artifacts.length,
    noteCount: task.notes.length,
    source: task.source,
  };
}

export function inferDispatchProgress(task: Pick<DispatchTask, 'status' | 'taskIntent' | 'mode' | 'progressDetail'>): DispatchTaskProgress {
  if (task.status === 'exporting') {
    return 'exporting';
  }

  if (task.status === 'executing') {
    if (task.taskIntent === 'research' || task.mode === 'research') {
      return 'researching';
    }

    if (task.taskIntent === 'procedural' || task.taskIntent === 'personal_workflow') {
      return 'editing';
    }

    return 'executing';
  }

  if (task.status === 'planning' || task.status === 'queued' || task.status === 'waiting_approval') {
    if (task.taskIntent === 'research' || task.mode === 'research') {
      return 'researching';
    }

    return 'thinking';
  }

  return 'thinking';
}
