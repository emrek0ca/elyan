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

const mockDecideExecution = vi.fn(async () => ({
  mode: 'task' as const,
  modelId: 'local:model-a',
  modelPerformance: 0.5,
  tools: {
    allowWebSearch: false,
    allowConnectors: true,
    allowLocalTools: true,
    allowBrowser: true,
    preferredTools: ['local_tools'],
  },
  steps: {
    complexity: 'medium' as const,
    stepBudget: 3,
    retryLimit: 1,
  },
  reasoning: ['mock decision'],
  artifactCount: 1,
}));

const mockedPlan = {
  taskIntent: 'personal_workflow',
  executionMode: 'single',
  routingMode: 'local_first',
  reasoningDepth: 'standard',
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
  usageBudget: {
    inference: 0,
    retrieval: 0,
    integrations: 0,
    evaluation: 0,
  },
  surface: { local: { capabilities: [], bridgeTools: [] }, mcp: { servers: [], tools: [], resources: [], resourceTemplates: [], prompts: [] } },
};

let executionAttempts = 0;

vi.mock('@/core/control-plane', () => ({
  getControlPlaneService: vi.fn(() => mockControlPlaneService),
  isControlPlaneSessionConfigured: vi.fn(() => true),
}));

vi.mock('@/core/providers', () => ({
  registry: {
    listAvailableModels: vi.fn(async () => [
      { id: 'local:model-a', type: 'local', provider: 'ollama', name: 'Local A' },
      { id: 'cloud:model-b', type: 'cloud', provider: 'openai', name: 'Cloud B' },
    ]),
    resolvePreferredModelId: vi.fn((selection: { preferredModelId?: string }) => selection.preferredModelId ?? 'local:model-a'),
    resolveModel: vi.fn((modelId: string) => ({
      provider: { id: modelId.startsWith('cloud:') ? 'openai' : 'ollama' },
      model: {},
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
    executeText: vi.fn(async () => {
      executionAttempts += 1;

      if (executionAttempts === 1) {
        throw new Error('timeout');
      }

      return {
        text: 'Recovered answer',
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

describe('interaction orchestrator completion behavior', () => {
  it('retries once before succeeding when the first execution attempt fails', async () => {
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
      intent: 'complete this task reliably',
      artifacts: [
        {
          id: 'artifact_plan',
          runId: 'run_1',
          kind: 'plan',
          title: 'Plan',
          content: 'Plan',
          createdAt: new Date().toISOString(),
          metadata: {},
        },
      ],
      steps: [],
      notes: [],
      continuity: {
        summary: 'test',
        nextSteps: [],
        openItemCount: 0,
        lastActivityAt: new Date().toISOString(),
      },
      verification: {
        status: 'not_run',
        summary: 'Verification has not run yet.',
      },
    });

    const { executeInteractionText } = await import('@/core/interaction/orchestrator');
    const result = await executeInteractionText({
      source: 'web',
      text: 'complete this task reliably',
      controlPlaneSession: {
        sub: 'usr_1',
        accountId: 'acct_1',
      },
    });

    expect(result.text).toBe('Recovered answer');
    expect(executionAttempts).toBe(2);
    expect(mockDecideExecution).toHaveBeenCalledTimes(1);
    expect(mockControlPlaneService.recordInteraction).toHaveBeenCalledTimes(1);
  });

  it('runs quantum optimization through the hybrid solver without calling the answer engine', async () => {
    executionAttempts = 0;
    mockDecideExecution.mockResolvedValueOnce({
      mode: 'quantum' as const,
      modelId: 'elyan:quantum-hybrid',
      modelPerformance: 0.5,
      tools: {
        allowWebSearch: false,
        allowConnectors: false,
        allowLocalTools: true,
        allowBrowser: false,
        preferredTools: ['optimization_solve', 'tool_bridge'],
      },
      steps: {
        complexity: 'medium' as const,
        stepBudget: 3,
        retryLimit: 1,
      },
      reasoning: ['mode=quantum'],
      artifactCount: 0,
    });
    mockControlPlaneService.getAccount.mockResolvedValue({
      entitlements: {
        hostedAccess: false,
        hostedUsageAccounting: false,
        hostedImprovementSignals: true,
      },
    });
    mockControlPlaneService.getInteractionContext.mockResolvedValue({
      contextBlocks: [],
    });
    mockControlPlaneService.recordInteraction.mockResolvedValue({
      thread: { threadId: 'web:thread-quantum' },
      memoryItem: { memoryId: 'mem_quantum' },
      learningDraft: undefined,
      messages: [],
    });
    mockRunStore.create.mockResolvedValue({
      id: 'run_quantum',
      mode: 'auto',
      intent: 'Solve this assignment optimization',
      artifacts: [],
      steps: [],
      notes: [],
      continuity: {
        summary: 'test',
        nextSteps: [],
        openItemCount: 0,
        lastActivityAt: new Date().toISOString(),
      },
      verification: {
        status: 'not_run',
        summary: 'Verification has not run yet.',
      },
    });

    const { executeInteractionText } = await import('@/core/interaction/orchestrator');
    const result = await executeInteractionText({
      source: 'web',
      text: 'Solve this assignment optimization: {"type":"assignment","workers":["w1","w2"],"tasks":["t1","t2"],"costs":{"w1":{"t1":1,"t2":2},"w2":{"t1":2,"t2":100}}}',
      controlPlaneSession: {
        sub: 'usr_1',
        accountId: 'acct_1',
      },
    });

    expect(result.modelId).toBe('elyan:quantum-hybrid');
    expect(result.text).toContain('Quantum Hybrid Optimization Report');
    expect(result.text).toContain('No external quantum hardware was used');
    expect(executionAttempts).toBe(0);
  });
});
