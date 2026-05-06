import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockQuery = vi.fn();
const mockGetControlPlanePool = vi.fn(() => ({
  query: mockQuery,
}));

vi.mock('@/lib/env', () => ({
  env: {
    DATABASE_URL: 'postgres://example',
  },
}));

vi.mock('@/core/control-plane/database', () => ({
  getControlPlanePool: mockGetControlPlanePool,
}));

describe('decision engine', () => {
  beforeEach(() => {
    mockQuery.mockReset();
  });

  it('keeps short direct questions on the fast path and falls back to the requested model', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'What is Elyan?',
      taskType: 'direct_answer',
      requestedModelId: 'ollama:base',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('fast');
    expect(decision.modelId).toBe('ollama:base');
    expect(decision.tools).toMatchObject({
      allowWebSearch: false,
      allowConnectors: false,
      allowLocalTools: false,
      allowBrowser: false,
    });
    expect(decision.steps).toMatchObject({
      complexity: 'low',
      stepBudget: 1,
      retryLimit: 0,
    });
  });

  it('promotes research queries when safe artifacts indicate strong retrieval performance', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [
        {
          artifact_type: 'routing_hint',
          base_model: 'ollama:research-model',
          space_id: 'acct_1',
          score: '0.90',
          confidence_score: '0.92',
          metadata: {
            task_type: 'research',
            routing_hint: 'retrieval-first and cloud-preferred for evidence heavy work',
          },
          created_at: new Date().toISOString(),
        },
      ],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'What changed in AI search this week?',
      taskType: 'research',
      requestedModelId: 'ollama:fallback',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('research');
    expect(decision.modelId).toBe('ollama:research-model');
    expect(decision.tools).toMatchObject({
      allowWebSearch: true,
      allowConnectors: true,
      allowLocalTools: false,
      allowBrowser: true,
    });
    expect(decision.steps.stepBudget).toBe(3);
    expect(decision.reasoning.join(' ')).toContain('mode=research');
  });

  it('biases procedural requests toward task execution with local tools', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [
        {
          artifact_type: 'prompt_hint',
          base_model: 'ollama:task-model',
          space_id: 'acct_1',
          score: '0.82',
          confidence_score: '0.88',
          metadata: {
            task_type: 'procedural',
            routing_hint: 'local-first for workspace execution',
          },
          created_at: new Date().toISOString(),
        },
      ],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'Implement the file sync workflow and update the local docs',
      taskType: 'procedural',
      requestedModelId: 'ollama:fallback',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('task');
    expect(decision.modelId).toBe('ollama:task-model');
    expect(decision.tools).toMatchObject({
      allowWebSearch: false,
      allowConnectors: true,
      allowLocalTools: true,
      allowBrowser: true,
    });
    expect(decision.steps.complexity).toBe('high');
    expect(decision.steps.stepBudget).toBe(4);
  });

  it('routes structured route optimization work to quantum mode', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'Solve this route optimization problem: {"type":"graph","nodes":["a","b","c"],"costMatrix":[[0,2,5],[2,0,1],[5,1,0]],"start":"a"}',
      taskType: 'direct_answer',
      requestedModelId: 'ollama:fallback',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('quantum');
    expect(decision.modelId).toBe('elyan:quantum-hybrid');
    expect(decision.solverStrategy).toBe('classical_only');
    expect(decision.problemComplexity?.complexity).toBe('low');
    expect(decision.tools).toMatchObject({
      allowWebSearch: false,
      allowConnectors: false,
      allowLocalTools: true,
      allowBrowser: false,
      preferredTools: ['optimization_solve', 'tool_bridge'],
    });
    expect(decision.steps).toMatchObject({
      complexity: 'high',
      stepBudget: 3,
      retryLimit: 1,
    });
  });

  it('maps demo logistics requests to the logistics_routing scenario', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'demo logistics',
      taskType: 'direct_answer',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('quantum');
    expect(decision.scenario?.id).toBe('logistics_routing');
    expect(decision.scenario?.demoRequested).toBe(true);
    expect(decision.reasoning.join(' ')).toContain('scenario=logistics_routing');
  });

  it('selects a hybrid solver strategy for medium optimization problems', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'Optimize this assignment problem: {"type":"assignment","workers":[{"id":"w1"},{"id":"w2"},{"id":"w3"},{"id":"w4"}],"tasks":[{"id":"t1"},{"id":"t2"},{"id":"t3"},{"id":"t4"}],"costs":{"w1":{"t1":1,"t2":9,"t3":8,"t4":7},"w2":{"t1":9,"t2":1,"t3":7,"t4":8},"w3":{"t1":8,"t2":7,"t3":1,"t4":9},"w4":{"t1":7,"t2":8,"t3":9,"t4":1}}}',
      taskType: 'direct_answer',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('quantum');
    expect(decision.solverStrategy).toBe('hybrid');
    expect(decision.problemComplexity?.complexity).toBe('medium');
  });

  it('selects a quantum-biased solver strategy for large optimization problems', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'Solve this resource allocation problem: {"type":"allocation","resources":[{"id":"r1"},{"id":"r2"},{"id":"r3"},{"id":"r4"},{"id":"r5"},{"id":"r6"},{"id":"r7"},{"id":"r8"}],"locations":[{"id":"z1"},{"id":"z2"},{"id":"z3"},{"id":"z4"},{"id":"z5"},{"id":"z6"},{"id":"z7"},{"id":"z8"}],"costs":{"r1":{"z1":1,"z2":2,"z3":3,"z4":4,"z5":5,"z6":6,"z7":7,"z8":8},"r2":{"z1":2,"z2":1,"z3":4,"z4":5,"z5":6,"z6":7,"z7":8,"z8":9},"r3":{"z1":3,"z2":4,"z3":1,"z4":6,"z5":7,"z6":8,"z7":9,"z8":10},"r4":{"z1":4,"z2":5,"z3":6,"z4":1,"z5":8,"z6":9,"z7":10,"z8":11},"r5":{"z1":5,"z2":6,"z3":7,"z4":8,"z5":1,"z6":10,"z7":11,"z8":12},"r6":{"z1":6,"z2":7,"z3":8,"z4":9,"z5":10,"z6":1,"z7":12,"z8":13},"r7":{"z1":7,"z2":8,"z3":9,"z4":10,"z5":11,"z6":12,"z7":1,"z8":14},"r8":{"z1":8,"z2":9,"z3":10,"z4":11,"z5":12,"z6":13,"z7":14,"z8":1}}}',
      taskType: 'direct_answer',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('quantum');
    expect(decision.solverStrategy).toBe('quantum_biased');
    expect(decision.problemComplexity?.complexity).toBe('high');
  });

  it('routes scheduling and allocation solving requests to quantum mode', async () => {
    mockQuery.mockResolvedValue({
      rows: [],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const scheduling = await decideExecution({
      query: 'Schedule workers to jobs with minimum cost: {"type":"scheduling","workers":["w1","w2"],"tasks":["t1","t2"],"costs":{"w1":{"t1":5,"t2":1},"w2":{"t1":1,"t2":5}}}',
      taskType: 'procedural',
      spaceId: 'acct_1',
    });
    const allocation = await decideExecution({
      query: 'Find the best resource allocation for these trucks and zones: {"type":"allocation","resources":["r1","r2"],"locations":["z1","z2"],"costs":{"r1":{"z1":8,"z2":1},"r2":{"z1":2,"z2":7}}}',
      taskType: 'procedural',
      spaceId: 'acct_1',
    });

    expect(scheduling.mode).toBe('quantum');
    expect(allocation.mode).toBe('quantum');
  });

  it('keeps conceptual optimization questions out of quantum mode', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'What is optimization?',
      taskType: 'direct_answer',
      requestedModelId: 'ollama:base',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('fast');
  });

  it('uses safe quantum artifacts to choose a deterministic solver preference', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [
        {
          artifact_type: 'routing_hint',
          base_model: 'unknown',
          space_id: 'acct_1',
          score: '0.91',
          confidence_score: '0.93',
          metadata: {
            decision_mode: 'quantum',
            problem_type: 'graph',
            solver_used: 'simulated_annealing',
            solution_quality: 0.92,
            improvement_ratio: 0.18,
            routing_hint: 'Quantum optimization tasks should use optimization_solve locally.',
          },
          created_at: new Date().toISOString(),
        },
      ],
    });

    const { decideExecution } = await import('@/core/decision/engine');
    const decision = await decideExecution({
      query: 'Optimize this graph route: {"type":"graph","nodes":["a","b","c"],"costMatrix":[[0,3,9],[3,0,1],[9,1,0]],"start":"a"}',
      taskType: 'direct_answer',
      spaceId: 'acct_1',
    });

    expect(decision.mode).toBe('quantum');
    expect(decision.solverPreference).toMatchObject({
      solverId: 'simulated_annealing',
      problemType: 'graph',
    });
    expect(decision.reasoning.join(' ')).toContain('solver_preference=simulated_annealing');
  });
});
