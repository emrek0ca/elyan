import { z } from 'zod';
import type { SearchMode, ScrapedContent } from '@/types/search';
import type { ModelRoutingMode, OrchestrationPlan, TeamRole } from '@/core/orchestration';

export const teamRoleSchema = z.enum([
  'planner',
  'researcher',
  'executor',
  'reviewer',
  'verifier',
  'memory_curator',
]);

export const teamPermissionSchema = z.enum([
  'read_context',
  'use_retrieval',
  'use_local_capability',
  'use_mcp',
  'use_browser_read',
  'request_action',
  'write_memory',
]);

export const teamTaskKindSchema = z.enum([
  'analysis',
  'research',
  'execution',
  'review',
  'verification',
  'memory',
]);

export const teamTaskStatusSchema = z.enum(['pending', 'running', 'completed', 'failed', 'blocked']);
export const teamMessageTypeSchema = z.enum(['task_result', 'question', 'blocker', 'decision', 'verification']);
export const teamEventTypeSchema = z.enum([
  'run_started',
  'plan_created',
  'task_started',
  'message_recorded',
  'artifact_recorded',
  'task_completed',
  'task_failed',
  'verification_completed',
  'run_completed',
  'run_failed',
]);

export const teamArtifactKindSchema = z.enum(['note', 'research', 'execution', 'review', 'verification', 'memory']);
export const teamVerificationStateSchema = z.enum([
  'passed',
  'failed',
  'missing_artifact',
  'unstructured',
  'error',
]);

export const teamVerificationSchema = z.object({
  passed: z.boolean(),
  summary: z.string().min(1),
  state: teamVerificationStateSchema.default('passed'),
  artifactId: z.string().min(1).optional(),
  rawContent: z.string().optional(),
});

export const teamAgentSchema = z.object({
  id: z.string().min(1),
  role: teamRoleSchema,
  title: z.string().min(1),
  modelRoutingMode: z.enum(['local_only', 'local_first', 'balanced', 'cloud_preferred']),
  permissions: z.array(teamPermissionSchema).default([]),
  systemPrompt: z.string().min(1),
});

export const teamTaskSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  kind: teamTaskKindSchema,
  assignedRole: teamRoleSchema,
  dependsOn: z.array(z.string().min(1)).default([]),
  requiresConfirmation: z.boolean().default(false),
  status: teamTaskStatusSchema.default('pending'),
});

export const teamPlanSchema = z.object({
  runId: z.string().min(1),
  createdAt: z.string().datetime(),
  query: z.string().min(1),
  mode: z.enum(['speed', 'research']),
  requestedModelId: z.string().optional(),
  modelRoutingMode: z.enum(['local_only', 'local_first', 'balanced', 'cloud_preferred']),
  maxConcurrentAgents: z.number().int().min(1).max(4),
  maxTasksPerRun: z.number().int().min(2).max(12),
  allowCloudEscalation: z.boolean(),
  agents: z.array(teamAgentSchema).min(1),
  tasks: z.array(teamTaskSchema).min(1),
  policy: z.object({
    reasons: z.array(z.string()).min(1),
    riskBoundary: z.enum(['read_only', 'confirmation_required']),
    sourcePlanTaskIntent: z.string().min(1),
    sourcePlanMode: z.string().min(1),
  }),
});

export const teamMessageSchema = z.object({
  id: z.string().min(1),
  runId: z.string().min(1),
  fromAgentId: z.string().min(1),
  toAgentId: z.string().min(1).optional(),
  taskId: z.string().min(1).optional(),
  type: teamMessageTypeSchema,
  content: z.string(),
  createdAt: z.string().datetime(),
});

export const teamArtifactSchema = z.object({
  id: z.string().min(1),
  runId: z.string().min(1),
  taskId: z.string().min(1),
  agentId: z.string().min(1),
  kind: teamArtifactKindSchema,
  title: z.string().min(1),
  content: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({}),
  createdAt: z.string().datetime(),
});

export const teamEventSchema = z.object({
  id: z.string().min(1),
  runId: z.string().min(1),
  type: teamEventTypeSchema,
  createdAt: z.string().datetime(),
  taskId: z.string().min(1).optional(),
  agentId: z.string().min(1).optional(),
  message: teamMessageSchema.optional(),
  artifact: teamArtifactSchema.optional(),
  data: z.record(z.string(), z.unknown()).default({}),
});

export const teamRunSummarySchema = z.object({
  runId: z.string().min(1),
  status: z.enum(['completed', 'failed']),
  createdAt: z.string().datetime(),
  finishedAt: z.string().datetime(),
  query: z.string().min(1),
  mode: z.enum(['speed', 'research']),
  modelId: z.string().min(1),
  modelProvider: z.string().min(1),
  taskCount: z.number().int().nonnegative(),
  agentCount: z.number().int().nonnegative(),
  verifier: z.object({
    passed: z.boolean(),
    summary: z.string(),
    state: teamVerificationStateSchema.default('passed'),
    artifactId: z.string().min(1).optional(),
  }),
  finalText: z.string(),
  artifactCount: z.number().int().nonnegative(),
  sourceCount: z.number().int().nonnegative(),
});

export type TeamPermission = z.infer<typeof teamPermissionSchema>;
export type TeamTaskKind = z.infer<typeof teamTaskKindSchema>;
export type TeamTaskStatus = z.infer<typeof teamTaskStatusSchema>;
export type TeamMessageType = z.infer<typeof teamMessageTypeSchema>;
export type TeamEventType = z.infer<typeof teamEventTypeSchema>;
export type TeamArtifactKind = z.infer<typeof teamArtifactKindSchema>;
export type TeamVerificationState = z.infer<typeof teamVerificationStateSchema>;
export type TeamVerification = z.infer<typeof teamVerificationSchema>;
export type TeamAgent = z.infer<typeof teamAgentSchema>;
export type TeamTask = z.infer<typeof teamTaskSchema>;
export type TeamPlan = z.infer<typeof teamPlanSchema>;
export type TeamMessage = z.infer<typeof teamMessageSchema>;
export type TeamArtifact = z.infer<typeof teamArtifactSchema>;
export type TeamEvent = z.infer<typeof teamEventSchema>;
export type TeamRunSummary = z.infer<typeof teamRunSummarySchema>;

export type TeamPlannerInput = {
  query: string;
  mode: SearchMode;
  requestedModelId?: string;
  sourcePlan: OrchestrationPlan;
  maxConcurrentAgents: number;
  maxTasksPerRun: number;
  allowCloudEscalation: boolean;
};

export type TeamRunInput = TeamPlannerInput & {
  contextAugments?: string[];
  searchEnabled: boolean;
  signal?: AbortSignal;
  abortSignal?: AbortSignal;
  maxExecutionMs?: number;
};

export type TeamRunResult = {
  text: string;
  sources: ScrapedContent[];
  teamPlan: TeamPlan;
  summary: TeamRunSummary;
  artifacts: TeamArtifact[];
  messages: TeamMessage[];
  modelId: string;
  modelProvider: string;
};

export type TeamAgentExecutionInput = {
  agent: TeamAgent;
  task: TeamTask;
  teamPlan: TeamPlan;
  query: string;
  modelId: string;
  modelProvider: string;
  sourceContext: string;
  contextBlocks: string[];
  artifacts: TeamArtifact[];
  messages: TeamMessage[];
  signal?: AbortSignal;
};

export type TeamAgentExecutor = (input: TeamAgentExecutionInput) => Promise<string>;
export type TeamRoleDefinition = {
  role: TeamRole;
  title: string;
  permissions: TeamPermission[];
  systemPrompt: string;
  modelRoutingMode: ModelRoutingMode;
};
