import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mockQuery = vi.fn();
const mockGetControlPlanePool = vi.fn(() => ({
  query: mockQuery,
}));

vi.mock('@/core/control-plane/database', () => ({
  getControlPlanePool: mockGetControlPlanePool,
}));

describe('learning signal extractor', () => {
  beforeEach(() => {
    mockQuery.mockReset();
    mockGetControlPlanePool.mockClear();
    process.env.DATABASE_URL = 'postgres://example';
  });

  afterEach(() => {
    delete process.env.DATABASE_URL;
  });

  it('derives safe learning signals and reusable artifact drafts', async () => {
    const { deriveLearningSignal, buildLearningArtifacts, buildLearningRetrievalText } = await import(
      '@/core/control-plane/learning/signal-extractor'
    );

    const signal = deriveLearningSignal({
      accountId: 'acct_1',
      eventId: 'evt_1',
      requestId: 'req_1',
      source: 'web',
      input: 'How do I do this?',
      output: 'Use the documented steps.',
      intent: 'direct_answer',
      taskType: 'research',
      success: true,
      latencyMs: 1200,
      score: 0.86,
      accepted: true,
      modelId: 'openai:gpt-4o',
      modelProvider: 'openai',
      isSafeForLearning: true,
      metadata: {
        source_count: 2,
        citation_count: 1,
        queryLength: 17,
        routingMode: 'cloud_preferred',
        reasoningDepth: 'deep',
        teacherStrategy: 'llm',
        evaluatorNotes: 'Strong answer',
        discardReason: '',
      },
      feedback: {
        rating: 5,
      },
    });

    expect(signal.taskType).toBe('research');
    expect(signal.isSafeForLearning).toBe(true);
    expect(signal.promptHint).toContain('evidence');
    expect(signal.routingHint).toContain('retrieval-first');
    expect(signal.toolUsagePattern).toContain('retrieval');

    const artifacts = buildLearningArtifacts(signal);
    expect(artifacts).toHaveLength(3);
    expect(artifacts.map((artifact) => artifact.artifactType)).toEqual(
      expect.arrayContaining(['prompt_hint', 'routing_hint', 'tool_usage_pattern'])
    );
    expect(artifacts[0]?.sourceEventIds).toEqual(['evt_1']);
    expect(artifacts[0]?.isSafeForLearning).toBe(true);

    const retrievalText = buildLearningRetrievalText(signal, artifacts);
    expect(retrievalText).toContain('task_type: research');
    expect(retrievalText).toContain('prompt_hint:');
    expect(retrievalText).not.toContain('How do I do this?');
    expect(retrievalText).not.toContain('Use the documented steps.');
  });

  it('loads only safe learning hints relevant to the task and model', async () => {
    mockQuery.mockResolvedValueOnce({
      rows: [
        {
          model_version: 'learning-prompt_hint-research-openai-gpt-4o',
          artifact_type: 'prompt_hint',
          base_model: 'openai:gpt-4o',
          source_event_ids: ['evt_1'],
          confidence_score: '0.92',
          metadata: {
            task_type: 'research',
            model_id: 'openai:gpt-4o',
            prompt_hint: 'Use evidence first.',
          },
          created_at: new Date().toISOString(),
        },
      ],
    });

    const { loadLearningPromptHints } = await import('@/core/control-plane/learning/signal-extractor');
    await expect(
      loadLearningPromptHints({
        taskType: 'research',
        modelId: 'openai:gpt-4o',
      })
    ).resolves.toEqual([expect.stringContaining('Use evidence first.')]);
  });
});
