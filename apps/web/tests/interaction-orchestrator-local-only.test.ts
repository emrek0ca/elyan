import { describe, expect, it, vi } from 'vitest';

const mockControlPlaneService = {
  getAccount: vi.fn(),
  getInteractionContext: vi.fn(),
  recordInteraction: vi.fn(),
  recordEvaluationSignal: vi.fn(),
};

const mockRunStore = {
  create: vi.fn(),
};

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
  surface: { local: { capabilities: [], bridgeTools: [] }, mcp: { servers: [], tools: [], resources: [], resourceTemplates: [], prompts: [] } },
};

vi.mock('@/core/control-plane', () => ({
  getControlPlaneService: vi.fn(() => mockControlPlaneService),
  isControlPlaneSessionConfigured: vi.fn(() => true),
}));

vi.mock('@/core/providers', () => ({
  registry: {
    resolvePreferredModelId: vi.fn(() => 'local-test-model'),
    resolveModel: vi.fn(() => ({
      provider: { id: 'local-provider' },
    })),
  },
}));

vi.mock('@/core/runtime-settings', () => ({
  readRuntimeSettingsSync: vi.fn(() => ({
    routing: {
      preferredModelId: undefined,
      searchEnabled: false,
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
    expect(mockControlPlaneService.recordInteraction).toHaveBeenCalledTimes(1);
    expect(mockControlPlaneService.recordEvaluationSignal).not.toHaveBeenCalled();
    },
    30_000
  );
});
