import type { SearchMode } from '@/types/search';

export type TaskIntent =
  | 'direct_answer'
  | 'research'
  | 'comparison'
  | 'procedural'
  | 'personal_workflow';

export type ReasoningDepth = 'shallow' | 'standard' | 'deep';
export type IntentConfidence = 'low' | 'medium' | 'high';
export type UncertaintyLevel = 'low' | 'medium' | 'high';

export type ModelRoutingMode = 'local_only' | 'local_first' | 'balanced' | 'cloud_preferred';
export type ExecutionMode = 'single' | 'team';
export type TeamRole =
  | 'planner'
  | 'researcher'
  | 'executor'
  | 'reviewer'
  | 'verifier'
  | 'memory_curator';

export type OrchestrationStage =
  | 'intent'
  | 'routing'
  | 'retrieval'
  | 'tooling'
  | 'synthesis'
  | 'citation'
  | 'evaluation';

export type CapabilityFamily =
  | 'retrieval'
  | 'tooling'
  | 'browser'
  | 'mcp'
  | 'documents'
  | 'charts'
  | 'calculation'
  | 'optimization';

export type CapabilityPolicyEntry = {
  capabilityId: string;
  family: CapabilityFamily;
  enabled: boolean;
  reason: string;
};

export type RetrievalPolicy = {
  rounds: number;
  maxUrls: number;
  rerankTopK: number;
  language: string;
  expandSearchQueries: boolean;
};

export type EvaluationPolicy = {
  collectRetrievalSignals: boolean;
  collectToolSignals: boolean;
  captureUsageSignals: boolean;
  promoteLearnings: boolean;
};

export type UsageBudget = {
  inference: number;
  retrieval: number;
  integrations: number;
  evaluation: number;
};

export type TeamPolicy = {
  enabledByDefault: boolean;
  reasons: string[];
  maxConcurrentAgents: number;
  maxTasksPerRun: number;
  allowCloudEscalation: boolean;
  modelRoutingMode: ModelRoutingMode;
  riskBoundary: 'read_only' | 'confirmation_required';
  requiredRoles: TeamRole[];
};

export type ExecutionObjectKind =
  | 'direct_answer'
  | 'local_capability'
  | 'local_bridge_tool'
  | 'mcp_tool'
  | 'mcp_resource'
  | 'mcp_prompt'
  | 'mcp_resource_template'
  | 'browser_read'
  | 'browser_automation'
  | 'crawl';

export type ExecutionTarget = {
  kind: ExecutionObjectKind;
  id?: string;
  title?: string;
  source: 'local' | 'mcp' | 'none';
  reason: string;
  requiresConfirmation: boolean;
};

export type SkillExecutionStageKind = 'analysis' | 'privacy' | 'capability' | 'mcp' | 'synthesis' | 'evaluation';

export type SkillExecutionStage = {
  id: string;
  title: string;
  summary: string;
  kind: SkillExecutionStageKind;
  requiresConfirmation: boolean;
  capabilityId?: string;
};

export type SkillExecutionTechnique = {
  id: string;
  title: string;
  category: string;
  reason: string;
  instruction: string;
  outputHint: string;
};

export type SkillExecutionCandidate = {
  skillId: string;
  title: string;
  version: string;
  domain: string;
  policyBoundary: 'local' | 'workspace' | 'hosted';
  outputShape: 'answer' | 'report' | 'artifact';
  preferredCapabilityIds: string[];
  score: number;
  reason: string;
  enabled: boolean;
  localOnly: boolean;
  sharedAllowed: boolean;
};

export type SkillExecutionDecision = {
  selectedSkillId: string;
  selectedSkillTitle: string;
  selectedSkillVersion: string;
  resultShape: 'answer' | 'report' | 'artifact';
  policyBoundary: 'local' | 'workspace' | 'hosted';
  preferredCapabilityIds: string[];
  requiresConfirmation: boolean;
  decisionSummary: string;
  fallbackReason?: string;
  notes: string[];
  candidates: SkillExecutionCandidate[];
  stages: SkillExecutionStage[];
  selectedTechniques: SkillExecutionTechnique[];
};

export type ExecutionPolicy = {
  preferredOrder: ExecutionObjectKind[];
  primary: ExecutionTarget;
  candidates: ExecutionTarget[];
  shouldRetrieve: boolean;
  shouldDiscoverMcp: boolean;
  shouldEscalateModel: boolean;
  requiresConfirmation: boolean;
  decisionSummary: string;
  fallbackReason?: string;
  notes: string[];
};

export type OrchestrationPlan = {
  stages: OrchestrationStage[];
  searchRounds: number;
  maxUrls: number;
  temperature: number;
  reasoningDepth: ReasoningDepth;
  taskIntent: TaskIntent;
  intentConfidence: IntentConfidence;
  uncertainty: UncertaintyLevel;
  routingMode: ModelRoutingMode;
  expandSearchQueries: boolean;
  retrieval: RetrievalPolicy;
  capabilityPolicy: CapabilityPolicyEntry[];
  evaluation: EvaluationPolicy;
  usageBudget: UsageBudget;
  executionMode: ExecutionMode;
  teamPolicy: TeamPolicy;
  surface: 'local' | 'shared-vps' | 'hosted';
  mode: SearchMode;
  executionPolicy: ExecutionPolicy;
  skillPolicy: SkillExecutionDecision;
};
