import { describe, expect, it } from 'vitest';
import { buildOperatorRun } from '@/core/operator/runs';
import { evaluateExecutionCompletion, type ExecutionCompletionArtifact } from '@/core/execution/completion-engine';

function buildArtifact(
  runId: string,
  kind: ExecutionCompletionArtifact['kind'],
  title: string,
  content: string,
  metadata: Record<string, unknown> = {}
): ExecutionCompletionArtifact {
  return {
    id: `artifact_${title.replace(/\s+/g, '_').toLowerCase()}`,
    runId,
    kind,
    title,
    content,
    createdAt: new Date().toISOString(),
    metadata,
  };
}

describe('execution completion engine', () => {
  it('returns success when research output is grounded and required artifacts are present', () => {
    const run = buildOperatorRun({
      source: 'cli',
      text: 'research local-first task completion patterns with sources',
      mode: 'research',
    });
    const decision = evaluateExecutionCompletion({
      run,
      steps: run.steps,
      outputs: [
        {
          text: 'Answer:\nGrounded result.\n\nSources:\n[1] Example - https://example.com',
          sources: [{ url: 'https://example.com', title: 'Example' }],
          success: true,
          modelId: 'ollama:local-test',
          modelProvider: 'ollama',
        },
      ],
      artifacts: [
        ...run.artifacts,
        buildArtifact(
          run.id,
          'research',
          'Research result',
          'Answer:\nGrounded result.\n\nSources:\n[1] Example - https://example.com',
          { sourceCount: 1 }
        ),
      ],
      attempt: 0,
      retryLimit: 1,
      taskIntent: 'research',
      routingMode: 'local_first',
    });

    expect(decision.verdict).toBe('success');
    expect(decision.verification.status).toBe('passed');
    expect(decision.shouldTriggerLearning).toBe(true);
  });

  it('requests a retry when research output lacks grounded evidence', () => {
    const run = buildOperatorRun({
      source: 'cli',
      text: 'research local-first task completion patterns with sources',
      mode: 'research',
    });
    const decision = evaluateExecutionCompletion({
      run,
      steps: run.steps,
      outputs: [
        {
          text: 'Answer without citations.',
          sources: [],
          success: true,
          modelId: 'ollama:local-test',
          modelProvider: 'ollama',
        },
      ],
      artifacts: [
        ...run.artifacts,
        buildArtifact(run.id, 'research', 'Research result', 'Answer without citations.', { sourceCount: 0 }),
      ],
      attempt: 0,
      retryLimit: 1,
      taskIntent: 'research',
      routingMode: 'local_first',
    });

    expect(decision.verdict).toBe('retry');
    expect(decision.retryPlan?.modelStrategy).toBe('alternate');
    expect(decision.retryPlan?.toolVariation).toBe('search');
    expect(decision.retryPlan?.searchEnabled).toBe(true);
    expect(decision.verification.status).toBe('blocked');
  });

  it('fails when a task output contains an error and retry budget is exhausted', () => {
    const run = buildOperatorRun({
      source: 'cli',
      text: 'finish the task with a clean completion summary',
      mode: 'cowork',
    });
    const decision = evaluateExecutionCompletion({
      run,
      steps: run.steps,
      outputs: [
        {
          text: 'Execution failed with a timeout.',
          sources: [],
          success: false,
          failureReason: 'timeout',
          modelId: 'ollama:local-test',
          modelProvider: 'ollama',
        },
      ],
      artifacts: [
        ...run.artifacts,
        buildArtifact(run.id, 'summary', 'Completion attempt', 'Execution failed with a timeout.'),
      ],
      attempt: 1,
      retryLimit: 1,
      taskIntent: 'personal_workflow',
      routingMode: 'local_first',
    });

    expect(decision.verdict).toBe('failure');
    expect(decision.finalRunStatus).toBe('failed');
    expect(decision.verification.status).toBe('failed');
  });
});
