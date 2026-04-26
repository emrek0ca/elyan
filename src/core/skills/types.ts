import { z } from 'zod';
import type { SearchMode } from '@/types/search';
import type { TaskIntent } from '@/core/orchestration/types';

const skillTaskIntentValues = ['direct_answer', 'research', 'comparison', 'procedural', 'personal_workflow'] as const;

export const skillDomainSchema = z.enum([
  'research',
  'operator',
  'documents',
  'browser',
  'mcp',
  'calculation',
  'general',
]);

export const skillTaskIntentSchema = z.enum(skillTaskIntentValues);
export const skillOutputShapeSchema = z.enum(['answer', 'report', 'artifact']);
export const skillPolicyBoundarySchema = z.enum(['local', 'workspace', 'hosted']);
export const skillAuditModeSchema = z.enum(['full', 'summary', 'redacted']);
export const skillStageKindSchema = z.enum(['analysis', 'privacy', 'capability', 'mcp', 'synthesis', 'evaluation']);
export const skillRiskLevelSchema = z.enum(['read_only', 'write_safe', 'write_sensitive', 'destructive', 'system_critical']);
export const skillApprovalLevelSchema = z.enum(['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA']);
export const skillVerificationModeSchema = z.enum(['none', 'summary', 'trace', 'artifact']);
export const skillContractSchema = z.object({
  summary: z.string().min(1),
  schema: z.record(z.string(), z.unknown()).optional(),
});

export const skillTriggerSchema = z.object({
  keywords: z.array(z.string().min(1)).default([]),
  intents: z.array(skillTaskIntentSchema).default([]),
  urlSensitive: z.boolean().default(false),
  documentSensitive: z.boolean().default(false),
  mcpSensitive: z.boolean().default(false),
  actionSensitive: z.boolean().default(false),
});

export const skillStageTemplateSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  kind: skillStageKindSchema,
  requiresConfirmation: z.boolean().default(false),
  capabilityId: z.string().min(1).optional(),
});

export const skillManifestSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  version: z.string().min(1),
  description: z.string().min(1),
  domain: skillDomainSchema,
  enabled: z.boolean(),
  source: z.object({
    kind: z.literal('builtin'),
  }),
  triggers: skillTriggerSchema,
  preferredCapabilityIds: z.array(z.string().min(1)).default([]),
  policyBoundary: skillPolicyBoundarySchema,
  localOnly: z.boolean(),
  sharedAllowed: z.boolean(),
  hostedAllowed: z.boolean(),
  externalActionsAllowed: z.boolean(),
  auditMode: skillAuditModeSchema,
  riskLevel: skillRiskLevelSchema.default('read_only'),
  approvalLevel: skillApprovalLevelSchema.default('AUTO'),
  inputContract: skillContractSchema.default({
    summary: 'Natural-language task intent plus selected runtime context.',
  }),
  outputContract: skillContractSchema.default({
    summary: 'Auditable answer, report, or artifact matching the selected output shape.',
  }),
  verificationMode: skillVerificationModeSchema.default('summary'),
  outputShape: skillOutputShapeSchema,
  selectionWeight: z.number().int().min(0).default(0),
  stageTemplates: z.array(skillStageTemplateSchema).default([]),
});

export const skillInstallationRecordSchema = z.object({
  id: z.string().min(1),
  source: z.string().min(1),
  sourceType: z.string().min(1),
  computedHash: z.string().min(1),
  version: z.string().min(1).default('locked'),
});

export type SkillDomain = z.output<typeof skillDomainSchema>;
export type SkillTaskIntent = z.output<typeof skillTaskIntentSchema>;
export type SkillOutputShape = z.output<typeof skillOutputShapeSchema>;
export type SkillPolicyBoundary = z.output<typeof skillPolicyBoundarySchema>;
export type SkillAuditMode = z.output<typeof skillAuditModeSchema>;
export type SkillStageKind = z.output<typeof skillStageKindSchema>;
export type SkillRiskLevel = z.output<typeof skillRiskLevelSchema>;
export type SkillApprovalLevel = z.output<typeof skillApprovalLevelSchema>;
export type SkillVerificationMode = z.output<typeof skillVerificationModeSchema>;
export type SkillContract = z.output<typeof skillContractSchema>;
export type SkillTrigger = z.output<typeof skillTriggerSchema>;
export type SkillStageTemplate = z.output<typeof skillStageTemplateSchema>;
export type SkillManifest = z.output<typeof skillManifestSchema>;
export type SkillInstallationRecord = z.output<typeof skillInstallationRecordSchema>;

export type SkillSelectionSurfaceSnapshot = {
  mcp?: {
    servers: number;
    tools: number;
    resources: number;
    resourceTemplates: number;
    prompts: number;
    discovery?: {
      attempted: boolean;
      status: 'skipped' | 'ready' | 'degraded' | 'unavailable';
      error?: string;
      cached?: boolean;
      lastHealthyAt?: string;
    };
  };
};

export type SkillDirectorySnapshot = {
  builtIn: SkillManifest[];
  installed: SkillInstallationRecord[];
  discovery: {
    attempted: boolean;
    status: 'skipped' | 'ready' | 'degraded' | 'unavailable';
    error?: string;
  };
  summary: {
    builtInSkillCount: number;
    enabledBuiltInSkillCount: number;
    installedSkillCount: number;
    localOnlySkillCount: number;
    workspaceScopedSkillCount: number;
    hostedAllowedSkillCount: number;
    mcpConfiguredServerCount: number;
    mcpEnabledServerCount: number;
    mcpDisabledServerCount: number;
    mcpDisabledToolCount: number;
    mcpConfigurationStatus: 'ready' | 'skipped' | 'unavailable';
    mcpConfigurationError?: string;
    approvalLevelCounts: Record<SkillApprovalLevel, number>;
    riskLevelCounts: Record<SkillRiskLevel, number>;
  };
  selectionGuide: Array<{
    kind: SkillDomain;
    title: string;
    when: string;
    why: string;
  }>;
};

export type SkillSelectionInput = {
  query: string;
  mode: SearchMode;
  taskIntent: TaskIntent;
  surface?: SkillSelectionSurfaceSnapshot;
};
