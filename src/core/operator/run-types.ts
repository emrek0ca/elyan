import { z } from 'zod';
import { localAgentApprovalLevelSchema, localAgentRiskLevelSchema } from '@/core/local-agent/types';

export const operatorRunModeSchema = z.enum(['auto', 'research', 'code', 'cowork']);
export const operatorRunSourceSchema = z.enum([
  'web',
  'telegram',
  'whatsapp_cloud',
  'whatsapp_baileys',
  'imessage_bluebubbles',
  'voice',
  'cli',
]);
export const operatorRunStatusSchema = z.enum(['planned', 'running', 'blocked', 'completed', 'failed', 'cancelled']);
export const operatorReasoningDepthSchema = z.enum(['shallow', 'standard', 'deep']);
export const operatorRunStepKindSchema = z.enum([
  'intent',
  'research',
  'repo_inspection',
  'planning',
  'execution',
  'review',
  'verification',
  'delivery',
  'memory',
]);
export const operatorRunStepStatusSchema = z.enum(['pending', 'running', 'completed', 'blocked', 'failed', 'skipped']);
export const operatorArtifactKindSchema = z.enum(['plan', 'research', 'patch', 'execution', 'review', 'verification', 'summary']);
export const operatorApprovalStatusSchema = z.enum(['pending', 'approved', 'rejected', 'expired']);
export const operatorWorkItemStatusSchema = z.enum(['open', 'done', 'blocked']);
export const operatorQualityGateStatusSchema = z.enum(['pending', 'passed', 'failed', 'blocked']);

export const operatorRunStepSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  kind: operatorRunStepKindSchema,
  status: operatorRunStepStatusSchema.default('pending'),
  requiresApproval: z.boolean().default(false),
  approvalId: z.string().min(1).optional(),
  riskLevel: localAgentRiskLevelSchema.optional(),
});

export const operatorArtifactSchema = z.object({
  id: z.string().min(1),
  runId: z.string().min(1),
  kind: operatorArtifactKindSchema,
  title: z.string().min(1),
  content: z.string(),
  createdAt: z.string().datetime(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export const operatorApprovalSchema = z.object({
  id: z.string().min(1),
  runId: z.string().min(1),
  stepId: z.string().min(1),
  status: operatorApprovalStatusSchema.default('pending'),
  title: z.string().min(1),
  reason: z.string().min(1),
  riskLevel: localAgentRiskLevelSchema,
  approvalLevel: localAgentApprovalLevelSchema,
  requestedAt: z.string().datetime(),
  resolvedAt: z.string().datetime().optional(),
  resolvedBy: z.string().min(1).optional(),
});

export const operatorVerificationSchema = z.object({
  status: z.enum(['not_run', 'passed', 'failed', 'blocked']).default('not_run'),
  summary: z.string().default('Verification has not run yet.'),
  checkedAt: z.string().datetime().optional(),
});

export const operatorWorkItemSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  status: operatorWorkItemStatusSchema.default('open'),
  sourceStepId: z.string().min(1).optional(),
  createdAt: z.string().datetime(),
  completedAt: z.string().datetime().optional(),
});

export const operatorContinuitySchema = z.object({
  summary: z.string().min(1),
  nextSteps: z.array(operatorWorkItemSchema).default([]),
  openItemCount: z.number().int().nonnegative().default(0),
  lastActivityAt: z.string().datetime(),
});

export const operatorReasoningProfileSchema = z.object({
  depth: operatorReasoningDepthSchema,
  maxPasses: z.number().int().min(1).max(8),
  halting: z.string().min(1),
  stabilityGuard: z.string().min(1),
  rationale: z.string().min(1),
});

export const operatorQualityGateSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  status: operatorQualityGateStatusSchema.default('pending'),
  evidence: z.string().min(1).optional(),
  checkedAt: z.string().datetime().optional(),
});

export const operatorRunSchema = z.object({
  id: z.string().min(1),
  version: z.literal(1),
  source: operatorRunSourceSchema,
  mode: operatorRunModeSchema,
  status: operatorRunStatusSchema,
  title: z.string().min(1),
  intent: z.string().min(1),
  createdAt: z.string().datetime(),
  updatedAt: z.string().datetime(),
  steps: z.array(operatorRunStepSchema).min(1),
  approvals: z.array(operatorApprovalSchema).default([]),
  artifacts: z.array(operatorArtifactSchema).default([]),
  verification: operatorVerificationSchema.default({
    status: 'not_run',
    summary: 'Verification has not run yet.',
  }),
  continuity: operatorContinuitySchema,
  reasoning: operatorReasoningProfileSchema,
  qualityGates: z.array(operatorQualityGateSchema).default([]),
  notes: z.array(z.string()).default([]),
});

export const createOperatorRunInputSchema = z.object({
  source: operatorRunSourceSchema.default('cli'),
  text: z.string().trim().min(1),
  mode: operatorRunModeSchema.default('auto'),
  title: z.string().trim().min(1).optional(),
});

export type OperatorRunMode = z.infer<typeof operatorRunModeSchema>;
export type OperatorRunSource = z.infer<typeof operatorRunSourceSchema>;
export type OperatorRunStatus = z.infer<typeof operatorRunStatusSchema>;
export type OperatorReasoningDepth = z.infer<typeof operatorReasoningDepthSchema>;
export type OperatorQualityGateStatus = z.infer<typeof operatorQualityGateStatusSchema>;
export type OperatorRunStep = z.infer<typeof operatorRunStepSchema>;
export type OperatorRun = z.infer<typeof operatorRunSchema>;
export type OperatorArtifact = z.infer<typeof operatorArtifactSchema>;
export type OperatorApproval = z.infer<typeof operatorApprovalSchema>;
export type OperatorWorkItem = z.infer<typeof operatorWorkItemSchema>;
export type OperatorReasoningProfile = z.infer<typeof operatorReasoningProfileSchema>;
export type OperatorQualityGate = z.infer<typeof operatorQualityGateSchema>;
export type CreateOperatorRunInput = z.infer<typeof createOperatorRunInputSchema>;
