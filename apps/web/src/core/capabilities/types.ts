import type { z, ZodTypeAny } from 'zod';

export type CapabilityStatus = 'success' | 'error' | 'disabled' | 'timeout';
export type CapabilityCategory =
  | 'documents'
  | 'research'
  | 'comms'
  | 'dev'
  | 'ops'
  | 'desktop'
  | 'memory'
  | 'browser'
  | 'calculation'
  | 'optimization'
  | 'general';
export type CapabilityRiskLevel = 'low' | 'medium' | 'high' | 'critical';
export type CapabilityApprovalLevel = 'AUTO' | 'CONFIRM' | 'SCREEN' | 'TWO_FA';
export type CapabilityVerificationMode = 'schema' | 'snapshot' | 'roundtrip' | 'manual' | 'audit';
export type CapabilityRollbackMode = 'none' | 'restore' | 'rebuild' | 'reversible' | 'manual';
export type CapabilitySource = 'local_module' | 'local_bridge_tool' | 'mcp_surface' | 'browser_surface' | 'direct';

export type CapabilityRuntimeContext = {
  taskId?: string;
  workspacePath?: string;
  browserSessionPath?: string;
  terminalSessionPath?: string;
  approvalCheckpointPath?: string;
  tracePath?: string;
  executionScope?: 'local' | 'dispatch' | 'operator';
  recoveryState?: 'fresh' | 'resumed' | 'recovered';
};

export type CapabilityOperationalProfile = {
  category: CapabilityCategory;
  riskLevel: CapabilityRiskLevel;
  approvalLevel: CapabilityApprovalLevel;
  verificationMode: CapabilityVerificationMode;
  rollbackMode: CapabilityRollbackMode;
  safeByDefault: boolean;
  useCases: string[];
  recommendedSkillId?: string;
};

export type CapabilityAuditEntry = {
  capabilityId: string;
  title: string;
  status: CapabilityStatus;
  startedAt: string;
  finishedAt: string;
  durationMs: number;
  errorMessage?: string;
};

export type CapabilityExecutionContext = {
  signal: AbortSignal;
  runtime?: CapabilityRuntimeContext;
};

export type CapabilityDefinition<
  InputSchema extends ZodTypeAny = ZodTypeAny,
  OutputSchema extends ZodTypeAny = ZodTypeAny,
> = {
  id: string;
  title: string;
  description: string;
  library: string;
  enabled: boolean;
  timeoutMs: number;
  inputSchema: InputSchema;
  outputSchema: OutputSchema;
  run: (
    input: z.output<InputSchema>,
    context: CapabilityExecutionContext
  ) => Promise<z.output<OutputSchema>> | z.output<OutputSchema>;
};

export type CapabilityRegistration = {
  disabledCapabilityIds?: string[];
};

export type CapabilityDirectoryEntry = {
  id: string;
  title: string;
  description: string;
  library: string;
  timeoutMs: number;
  enabled: boolean;
  source: CapabilitySource;
  profile: CapabilityOperationalProfile;
};

export type CapabilityDomainSnapshot = {
  category: CapabilityCategory;
  title: string;
  summary: string;
  capabilityIds: string[];
  libraries: string[];
  capabilityCount: number;
  enabledCapabilityCount: number;
  riskLevelCounts: Record<CapabilityRiskLevel, number>;
  approvalLevelCounts: Record<CapabilityApprovalLevel, number>;
  sourceCounts: Record<CapabilitySource, number>;
};
