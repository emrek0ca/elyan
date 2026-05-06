import { z } from 'zod';

export const localAgentApprovalLevelSchema = z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']);
export const localAgentRiskLevelSchema = z.enum([
  'read_only',
  'write_safe',
  'write_sensitive',
  'destructive',
  'system_critical',
]);

export const localAgentActionSchema = z.discriminatedUnion('type', [
  z.object({
    type: z.enum(['filesystem.list', 'filesystem.read_text']),
    path: z.string().trim().min(1),
    runId: z.string().trim().min(1).optional(),
    approved: z.boolean().optional(),
  }),
  z.object({
    type: z.enum(['filesystem.write_text', 'filesystem.patch_text']),
    path: z.string().trim().min(1),
    content: z.string(),
    runId: z.string().trim().min(1).optional(),
    approved: z.boolean().optional(),
  }),
  z.object({
    type: z.enum(['filesystem.move', 'filesystem.restore']),
    path: z.string().trim().min(1),
    targetPath: z.string().trim().min(1),
    runId: z.string().trim().min(1).optional(),
    approved: z.boolean().optional(),
  }),
  z.object({
    type: z.literal('filesystem.trash'),
    path: z.string().trim().min(1),
    runId: z.string().trim().min(1).optional(),
    approved: z.boolean().optional(),
  }),
  z.object({
    type: z.literal('terminal.exec'),
    cwd: z.string().trim().min(1),
    command: z.string().trim().min(1),
    args: z.array(z.string()).default([]),
    timeoutMs: z.number().int().positive().max(120_000).default(30_000),
    interactive: z.boolean().default(false),
    runId: z.string().trim().min(1).optional(),
    approved: z.boolean().optional(),
  }),
]);

export type LocalAgentApprovalLevel = z.infer<typeof localAgentApprovalLevelSchema>;
export type LocalAgentRiskLevel = z.infer<typeof localAgentRiskLevelSchema>;
export type LocalAgentAction = z.infer<typeof localAgentActionSchema>;

export type LocalAgentDecision = {
  allowed: boolean;
  riskLevel: LocalAgentRiskLevel;
  approvalLevel: LocalAgentApprovalLevel;
  reason: string;
  requiresConfirmation: boolean;
  normalizedPath?: string;
};

export type LocalAgentExecutionResult = {
  ok: boolean;
  actionType: LocalAgentAction['type'];
  runId: string;
  decision: LocalAgentDecision;
  output?: unknown;
  error?: string;
};
