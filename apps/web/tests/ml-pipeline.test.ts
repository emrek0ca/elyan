import { describe, expect, it } from 'vitest';
import {
  buildInteractionTrace,
  buildMlDatasetCandidates,
  buildMlDatasetRecord,
  buildMlDatasetSummary,
  buildQualityAssessment,
} from '@/core/ml';

describe('ml pipeline', () => {
  const accounts = [
    {
      account_id: 'acct_1',
      display_name: 'Ayla',
      owner_type: 'individual',
      status: 'active',
      plan_id: 'cloud_assisted',
      subscription_status: 'active',
      interaction_state: {
        threads: [
          {
            threadId: 'thr_1',
            intent: 'research',
            title: 'Research thread',
            summary: 'Summarize current routing',
            source: 'answer_engine',
            metadata: {
              intent: 'research',
            },
          },
        ],
        messages: [
          {
            messageId: 'msg_1',
            threadId: 'thr_1',
            role: 'user',
            content: 'Improve this answer',
            createdAt: '2026-04-23T10:00:00.000Z',
            metadata: {
              requestId: 'req_1',
            },
          },
          {
            messageId: 'msg_2',
            threadId: 'thr_1',
            role: 'assistant',
            content: 'Old answer',
            createdAt: '2026-04-23T10:01:00.000Z',
            metadata: {
              requestId: 'req_1',
            },
          },
        ],
        learningDrafts: [
          {
            draftId: 'ldr_1',
            threadId: 'thr_1',
            kind: 'research',
            title: 'Draft title',
            summary: 'Draft summary',
            body: 'Draft body',
            status: 'promoted',
            metadata: {},
          },
        ],
      },
      updated_at: '2026-04-23T10:01:00.000Z',
    },
  ];

  const signals = [
    {
      signal_id: 'sig_1',
      account_id: 'acct_1',
      request_id: 'req_1',
      payload: {
        quality: 'poor',
        routingMode: 'cloud_preferred',
        reasoningDepth: 'deep',
        latencyMs: 123,
        model: {
          provider: 'openai',
          modelId: 'gpt-4o',
        },
        retrieval: {
          sourceCount: 3,
          citationCount: 2,
        },
        tooling: {
          toolCallCount: 1,
          toolResultCount: 1,
        },
      },
      created_at: '2026-04-23T10:01:30.000Z',
    },
  ];

  const learningEvents = [
    {
      event_id: 'lgn_1',
      account_id: 'acct_1',
      request_id: 'req_1',
      source: 'web',
      input: 'Improve this answer',
      intent: 'research',
      plan: 'intent=research; routing=cloud_preferred; depth=deep',
      reasoning_steps: ['input: Improve this answer', 'intent: research'],
      reasoning_trace: ['input: Improve this answer', 'intent: research'],
      output: 'Old answer',
      better_output: 'Improved answer',
      success: true,
      failure_reason: null,
      latency_ms: 123,
      score: 0.9,
      accepted: true,
      model_id: 'gpt-4o',
      model_provider: 'openai',
      metadata: {
        citationCount: 2,
      },
      created_at: '2026-04-23T10:01:15.000Z',
    },
  ];

  it('builds dataset candidates from hosted interaction and learning state', () => {
    const candidates = buildMlDatasetCandidates(accounts, learningEvents, signals, { maxSamples: 10 });

    expect(candidates).toHaveLength(1);
    expect(candidates[0]).toMatchObject({
      account_id: 'acct_1',
      source: 'request',
      request_id: 'req_1',
      quality: 'good',
      better_output: 'Improved answer',
    });
    expect(candidates[0].plan).toContain('routing=cloud_preferred');
    expect(buildInteractionTrace(candidates[0]).join('\n')).toContain('plan:');
  });

  it('discards samples when the teacher is unavailable', async () => {
    const candidates = buildMlDatasetCandidates(accounts, learningEvents, signals, { maxSamples: 10 });
    const assessment = await buildQualityAssessment(candidates[0], null);

    expect(assessment).toMatchObject({
      accepted: false,
      discard_reason: 'teacher_unavailable',
      teacher_strategy: 'missing',
    });
  });

  it('builds clean dataset records and summaries', async () => {
    const candidates = buildMlDatasetCandidates(accounts, learningEvents, signals, { maxSamples: 10 });
    const record = await buildMlDatasetRecord(candidates[0], null);

    expect(record).not.toBeNull();
    expect(record).toMatchObject({
      better_output: 'Improved answer',
      accepted: true,
      model_role: 'teacher',
      request_id: 'req_1',
    });

    const summary = buildMlDatasetSummary([record!]);
    expect(summary).toMatchObject({
      record_count: 1,
      accepted_count: 1,
      discarded_count: 0,
      average_score: expect.any(Number),
    });
  });
});
