import { describe, expect, it } from 'vitest';
import { resolveAnswerPrompt } from '@/core/agents/answer-prompts';

describe('answer prompts', () => {
  it('adds artifact-specific lane instructions for workspace outputs', () => {
    const prompt = resolveAnswerPrompt(
      'speed',
      'context',
      true,
      {
        plan: {
          skillPolicy: {
            selectedSkillId: 'workspace_operator',
            resultShape: 'artifact',
          },
          routingMode: 'local_first',
        } as never,
      }
    );

    expect(prompt).toContain('Prefer copy-ready artifact output over commentary and keep the formatting clean, stable, and reusable.');
    expect(prompt).toContain('When the task is code, workspace, or design related');
    expect(prompt).toContain('Prefer the smallest local path before broader reasoning.');
  });

  it('makes fallback behavior explicit for general answers without sources', () => {
    const prompt = resolveAnswerPrompt(
      'research',
      'context',
      false,
      {
        plan: {
          skillPolicy: {
            selectedSkillId: 'general_answer',
            resultShape: 'answer',
          },
          routingMode: 'balanced',
        } as never,
      }
    );

    expect(prompt).toContain('State clearly that no specialized lane or verified sources were available');
    expect(prompt).toContain('Use the smallest trustworthy answer path');
  });
});
