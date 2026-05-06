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

  it('adds production artifact guidance for design producer outputs', () => {
    const prompt = resolveAnswerPrompt(
      'speed',
      'context',
      true,
      {
        plan: {
          skillPolicy: {
            selectedSkillId: 'design_producer',
            resultShape: 'artifact',
          },
          routingMode: 'local_first',
        } as never,
      }
    );

    expect(prompt).toContain('Treat design work as a production artifact');
    expect(prompt).toContain('avoid generic AI patterns');
  });

  it('adds selected technique guidance without requiring a new lane', () => {
    const prompt = resolveAnswerPrompt(
      'speed',
      'context',
      true,
      {
        plan: {
          skillPolicy: {
            selectedSkillId: 'document_inspector',
            resultShape: 'report',
            selectedTechniques: [
              {
                id: 'scqa-writing-framework',
                title: 'SCQA Writing Framework',
                category: 'writing_content',
                reason: 'keyword match: scqa',
                instruction: 'Use Situation, Complication, Question, and Answer sections.',
                outputHint: 'SCQA sections with short paragraphs.',
              },
            ],
          },
          routingMode: 'local_first',
        } as never,
      }
    );

    expect(prompt).toContain('Apply SCQA Writing Framework');
    expect(prompt).toContain('Use Situation, Complication, Question, and Answer sections.');
    expect(prompt).toContain('Output hint for SCQA Writing Framework');
  });

  it('adds canonical optimization guardrails for optimization decision output', () => {
    const prompt = resolveAnswerPrompt(
      'speed',
      'context',
      true,
      {
        plan: {
          skillPolicy: {
            selectedSkillId: 'optimization_decision',
            resultShape: 'report',
          },
          routingMode: 'local_first',
        } as never,
      }
    );

    expect(prompt).toContain('hybrid classical and quantum-inspired decision report');
    expect(prompt).toContain('not a real quantum hardware claim');
    expect(prompt).toContain('State the modeled problem, solver comparison, feasibility, and selected solution explicitly.');
  });
});
