import { mkdtemp, readFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockPersistLearningArtifacts = vi.fn();
const mockIngestRetrievalText = vi.fn();

vi.mock('@/core/control-plane/learning/signal-extractor', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/core/control-plane/learning/signal-extractor')>();

  return {
    ...actual,
    persistLearningArtifacts: mockPersistLearningArtifacts,
  };
});

vi.mock('@/core/retrieval', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/core/retrieval')>();

  return {
    ...actual,
    ingestRetrievalText: mockIngestRetrievalText,
  };
});

describe('hosted learning wiring', () => {
  const tempDirs: string[] = [];

  beforeEach(() => {
    mockPersistLearningArtifacts.mockReset();
    mockPersistLearningArtifacts.mockResolvedValue(undefined);
    mockIngestRetrievalText.mockReset();
    mockIngestRetrievalText.mockResolvedValue({ documentId: 'doc_learning_hint' });
  });

  afterEach(async () => {
    while (tempDirs.length > 0) {
      const dir = tempDirs.pop();
      if (dir) {
        await rm(dir, { recursive: true, force: true });
      }
    }
  });

  async function createService() {
    const dir = await mkdtemp(join(tmpdir(), 'elyan-control-plane-learning-'));
    tempDirs.push(dir);

    const { ControlPlaneService } = await import('@/core/control-plane');
    return {
      service: ControlPlaneService.create(join(dir, 'state.json')),
      statePath: join(dir, 'state.json'),
    };
  }

  it('promotes safe hosted learning events into artifacts and retrieval hints', async () => {
    const { service, statePath } = await createService();
    const created = await service.registerIdentity({
      email: 'learning-safe@example.com',
      password: 'very-strong-password',
      displayName: 'Learning Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_learning_safe',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_learning_safe',
        subscriptionReferenceCode: 'sub_learning_safe',
        orderReferenceCode: 'ord_learning_safe',
        iyziReferenceCode: 'ref_learning_safe',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const event = await service.recordLearningEvent(created.account.accountId, {
      requestId: 'req_learning_safe_1',
      source: 'web',
      input: 'How can I improve this response?',
      intent: 'direct_answer',
      taskType: 'research',
      plan: 'intent=direct_answer; routing=cloud_preferred; depth=deep',
      reasoningSteps: ['input: How can I improve this response?', 'intent: direct_answer'],
      output: 'Use evidence first and keep the answer concise.',
      success: true,
      latencyMs: 140,
      modelId: 'openai:gpt-4o',
      modelProvider: 'openai',
      feedback: {
        rating: 5,
        note: 'strong answer',
      },
      isSafeForLearning: true,
      metadata: {
        citationCount: 2,
        sourceCount: 1,
        queryLength: 32,
        routingMode: 'cloud_preferred',
        reasoningDepth: 'deep',
        teacherStrategy: 'llm',
        evaluatorNotes: 'Strong answer',
        problem_objective: 'weighted cost/time/efficiency',
        problem_complexity: 'medium',
        estimated_space: 40320,
        problem_size: 8,
        solver_strategy: 'hybrid',
      },
    });

    expect(event.taskType).toBe('research');
    expect(event.isSafeForLearning).toBe(true);
    expect(event.feedback).toEqual({
      rating: 5,
      note: 'strong answer',
    });

    expect(mockPersistLearningArtifacts).toHaveBeenCalledTimes(1);
    expect(mockIngestRetrievalText).toHaveBeenCalledTimes(1);
    expect(mockIngestRetrievalText.mock.calls[0]?.[0]).toEqual(
      expect.objectContaining({
        sourceKind: 'learning',
        sourceName: 'learning_signal',
        title: 'research learning signal',
      })
    );

    const retrievalContent = String(mockIngestRetrievalText.mock.calls[0]?.[0]?.content ?? '');
    expect(retrievalContent).toContain('task_type: research');
    expect(retrievalContent).toContain('prompt_hint:');
    expect(retrievalContent).toContain('problem_objective: weighted cost/time/efficiency');
    expect(retrievalContent).toContain('problem_complexity: medium');
    expect(retrievalContent).not.toContain('How can I improve this response?');
    expect(retrievalContent).not.toContain('Use evidence first');

    const state = JSON.parse(await readFile(statePath, 'utf8')) as {
      learningEvents: Array<{
        taskType: string;
        feedback: Record<string, unknown>;
        isSafeForLearning: boolean;
      }>;
    };
    expect(state.learningEvents).toHaveLength(1);
    expect(state.learningEvents[0]).toEqual(
      expect.objectContaining({
        taskType: 'research',
        isSafeForLearning: true,
      })
    );
    expect(state.learningEvents[0]?.feedback).toEqual({
      rating: 5,
      note: 'strong answer',
    });
  });

  it('keeps unsafe hosted events local to the canonical event log', async () => {
    const { service, statePath } = await createService();
    const created = await service.registerIdentity({
      email: 'learning-unsafe@example.com',
      password: 'very-strong-password',
      displayName: 'Learning Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_learning_unsafe',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_learning_unsafe',
        subscriptionReferenceCode: 'sub_learning_unsafe',
        orderReferenceCode: 'ord_learning_unsafe',
        iyziReferenceCode: 'ref_learning_unsafe',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    const event = await service.recordLearningEvent(created.account.accountId, {
      requestId: 'req_learning_unsafe_1',
      source: 'web',
      input: 'Private local notes should never leave the runtime.',
      intent: 'direct_answer',
      taskType: 'personal_workflow',
      plan: 'intent=direct_answer; routing=local_first; depth=standard',
      reasoningSteps: ['input: Private local notes should never leave the runtime.'],
      output: 'Do not upload the private notes.',
      success: true,
      latencyMs: 95,
      modelId: 'openai:gpt-4o',
      modelProvider: 'openai',
      feedback: {},
      isSafeForLearning: false,
      metadata: {
        citationCount: 0,
        sourceCount: 0,
        queryLength: 11,
        routingMode: 'local_first',
        reasoningDepth: 'standard',
        teacherStrategy: 'local',
      },
    });

    expect(event.taskType).toBe('personal_workflow');
    expect(event.isSafeForLearning).toBe(false);
    expect(mockPersistLearningArtifacts).not.toHaveBeenCalled();
    expect(mockIngestRetrievalText).not.toHaveBeenCalled();

    const state = JSON.parse(await readFile(statePath, 'utf8')) as {
      learningEvents: Array<{
        taskType: string;
        feedback: Record<string, unknown>;
        isSafeForLearning: boolean;
      }>;
    };
    expect(state.learningEvents).toHaveLength(1);
    expect(state.learningEvents[0]).toEqual(
      expect.objectContaining({
        taskType: 'personal_workflow',
        isSafeForLearning: false,
      })
    );
  });

  it('promotes safe quantum solver outcomes into routing and tool artifacts', async () => {
    const { service } = await createService();
    const created = await service.registerIdentity({
      email: 'learning-quantum@example.com',
      password: 'very-strong-password',
      displayName: 'Learning Quantum Owner',
      ownerType: 'individual',
      planId: 'cloud_assisted',
    });

    await service.upsertAccount(created.account.accountId, {
      displayName: created.account.displayName,
      ownerType: created.account.ownerType,
      planId: 'cloud_assisted',
      ownerUserId: created.user.userId,
      billingCustomerRef: 'cust_learning_quantum',
    });

    await service.applyIyzicoWebhook(
      {
        customerReferenceCode: 'cust_learning_quantum',
        subscriptionReferenceCode: 'sub_learning_quantum',
        orderReferenceCode: 'ord_learning_quantum',
        iyziReferenceCode: 'ref_learning_quantum',
        iyziEventType: 'subscription.order.success',
        iyziEventTime: Date.now(),
      },
      undefined,
      { bypassSignatureValidation: true }
    );

    await service.recordLearningEvent(created.account.accountId, {
      requestId: 'req_learning_quantum_1',
      source: 'web',
      input: 'Solve a structured route optimization problem.',
      intent: 'direct_answer',
      taskType: 'procedural',
      plan: 'intent=direct_answer; routing=local_first; depth=standard',
      reasoningSteps: ['decision_mode=quantum', 'tool=optimization_solve'],
      output: 'Quantum hybrid solver selected simulated_annealing.',
      success: true,
      latencyMs: 52,
      modelId: 'elyan:quantum-hybrid',
      modelProvider: 'elyan_quantum',
      feedback: {},
      isSafeForLearning: true,
      metadata: {
        sourceCount: 1,
        citationCount: 0,
        queryLength: 48,
        routingMode: 'local_first',
        reasoningDepth: 'standard',
        decision_mode: 'quantum',
        problem_type: 'graph',
        solver_used: 'simulated_annealing',
        solver_backend: 'quantum_inspired',
        solver_latency_ms: 52,
        baseline_cost: 101,
        selected_cost: 4,
        solution_quality: 0.94,
        solver_quality: 0.97,
        success_rate: 1,
        improvement_ratio: 0.96,
        solver_status: 'solved',
      },
    });

    expect(mockPersistLearningArtifacts).toHaveBeenCalledTimes(1);
    const drafts = mockPersistLearningArtifacts.mock.calls[0]?.[1] ?? [];
    const routingHint = drafts.find((draft: { artifactType: string }) => draft.artifactType === 'routing_hint');
    const toolPattern = drafts.find((draft: { artifactType: string }) => draft.artifactType === 'tool_usage_pattern');

    expect(routingHint?.metadata).toMatchObject({
      decision_mode: 'quantum',
      problem_type: 'graph',
      solver_used: 'simulated_annealing',
      solver_backend: 'quantum_inspired',
      solution_quality: 0.94,
      solver_quality: 0.97,
      success_rate: 1,
      improvement_ratio: 0.96,
    });
    expect(String(routingHint?.metadata.routing_hint)).toContain('optimization_solve');
    expect(String(toolPattern?.metadata.tool_usage_pattern)).toContain('compare classical and quantum-inspired candidates');
  });
});
