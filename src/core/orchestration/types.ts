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
  | 'calculation';

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
  surface: 'local' | 'shared-vps' | 'hosted';
  mode: SearchMode;
  executionPolicy: ExecutionPolicy;
};
