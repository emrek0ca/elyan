import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockControlPlaneService = {
  getAccount: vi.fn(),
  getInteractionContext: vi.fn(),
  recordUsageBundle: vi.fn(),
  recordInteraction: vi.fn(),
  recordLearningEvent: vi.fn(),
  recordEvaluationSignal: vi.fn(),
};

const mockRunStore = {
  create: vi.fn(),
};

const mockDecideExecution = vi.fn(async () => ({
  mode: 'research' as const,
  modelId: 'decision-model',
  modelPerformance: 0.92,
  tools: {
    allowWebSearch: false,
    allowConnectors: true,
    allowLocalTools: false,
    allowBrowser: false,
    preferredTools: ['connectors'],
  },
  steps: {
    complexity: 'medium' as const,
    stepBudget: 2,
    retryLimit: 1,
  },
  reasoning: ['mock decision'],
  artifactCount: 1,
}));

const mockedPlan = {
  taskIntent: 'direct_answer',
  executionMode: 'single',
  routingMode: 'local_first',
  reasoningDepth: 'shallow',
  teamPolicy: {
    enabledByDefault: false,
    modelRoutingMode: 'local_only',
    requiredRoles: [],
  },
  executionPolicy: {
    shouldRetrieve: false,
    notes: [],
    primary: { kind: 'direct_answer' },
  },
  retrieval: {
    rounds: 0,
    maxUrls: 0,
    rerankTopK: 0,
    language: 'en',
    expandSearchQueries: false,
  },
  surface: { local: { capabilities: [], bridgeTools: [] }, mcp: { servers: [], tools: [], resources: [], resourceTemplates: [], prompts: [] } },
};

vi.mock('@/core/control-plane', () => ({
  getControlPlaneService: vi.fn(() => mockControlPlaneService),
  isControlPlaneSessionConfigured: vi.fn(() => true),
}));

vi.mock('@/core/providers', () => ({
  registry: {
    resolvePreferredModelId: vi.fn((selection: { preferredModelId?: string }) => selection.preferredModelId ?? 'local-test-model'),
    resolveModel: vi.fn(() => ({
      provider: { id: 'local-provider' },
    })),
  },
}));

vi.mock('@/core/decision/engine', () => ({
  decideExecution: mockDecideExecution,
}));

vi.mock('@/core/runtime-settings', () => ({
  readRuntimeSettingsSync: vi.fn(() => ({
    routing: {
      preferredModelId: undefined,
      searchEnabled: true,
    },
    team: {
      enabled: false,
      defaultMode: 'auto',
      maxConcurrentAgents: 1,
      maxTasksPerRun: 2,
      allowCloudEscalation: false,
    },
  })),
}));

vi.mock('@/core/agents/answer-engine', () => ({
  answerEngine: {
    executeText: vi.fn(async (_text, _modelId, _mode, options) => {
      await options?.onFinish?.(
        { text: 'Local answer', totalUsage: {} },
        { sources: [], providerId: 'mock-provider' }
      );

      return {
        text: 'Local answer',
        sources: [],
        plan: mockedPlan,
      };
    }),
  },
}));

vi.mock('@/core/operator/runs', () => ({
  getOperatorRunStore: vi.fn(() => mockRunStore),
  recordOperatorRunArtifact: vi.fn(async () => undefined),
}));

vi.mock('@/core/orchestration', () => ({
  buildExecutionSurfaceSnapshot: vi.fn(() => mockedPlan.surface),
  buildOrchestrationPlan: vi.fn(() => mockedPlan),
}));

describe('interaction orchestrator local-only behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it(
    'records local interaction memory without writing hosted improvement signals',
    async () => {
      mockControlPlaneService.getAccount.mockResolvedValue({
        entitlements: {
          hostedAccess: false,
          hostedUsageAccounting: false,
          hostedImprovementSignals: false,
        },
      });
      mockControlPlaneService.getInteractionContext.mockResolvedValue({
        contextBlocks: [],
      });
      mockControlPlaneService.recordInteraction.mockResolvedValue({
        thread: { threadId: 'web:thread-1' },
        memoryItem: { memoryId: 'mem_1' },
        learningDraft: undefined,
        messages: [],
      });
      mockRunStore.create.mockResolvedValue({
        id: 'run_1',
        mode: 'auto',
      });

      const { executeInteractionText } = await import('@/core/interaction/orchestrator');
      const result = await executeInteractionText({
        source: 'web',
        text: 'Remember that I prefer concise answers.',
        controlPlaneSession: {
          sub: 'usr_1',
          accountId: 'acct_1',
        },
      });

      expect(result.text).toBe('Local answer');
      expect(mockDecideExecution).toHaveBeenCalledTimes(1);
      expect(mockDecideExecution.mock.invocationCallOrder[0]).toBeLessThan(mockRunStore.create.mock.invocationCallOrder[0]);
      expect(result.modelId).toBe('decision-model');
      expect(mockControlPlaneService.recordInteraction).toHaveBeenCalledTimes(1);
      expect(mockControlPlaneService.recordEvaluationSignal).not.toHaveBeenCalled();
      expect(mockRunStore.create).toHaveBeenCalled();
    },
    30_000
  );
});
