import { describe, expect, it } from 'vitest';
import { buildSkillDirectorySnapshot, buildSkillExecutionDecision } from '@/core/skills';

describe('Skill runtime', () => {
  it('selects the research companion for research-heavy queries', () => {
    const decision = buildSkillExecutionDecision({
      query: 'What changed in AI search this week?',
      mode: 'research',
      taskIntent: 'research',
    });

    expect(decision.selectedSkillId).toBe('research_companion');
    expect(decision.resultShape).toBe('report');
    expect(decision.preferredCapabilityIds).toEqual(expect.arrayContaining(['web_crawl', 'web_read_dynamic']));
  });

  it('keeps local workspace tasks on the operator skill', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Work on my files locally',
      mode: 'speed',
      taskIntent: 'personal_workflow',
    });

    expect(decision.selectedSkillId).toBe('workspace_operator');
    expect(decision.policyBoundary).toBe('local');
    expect(decision.requiresConfirmation).toBe(false);
  });

  it('reads installed skill lock records when building the skill directory', async () => {
    const directory = await buildSkillDirectorySnapshot(true);

    expect(directory.builtIn.length).toBeGreaterThan(0);
    expect(directory.summary.enabledBuiltInSkillCount).toBeGreaterThan(0);
    expect(directory.summary.installedSkillCount).toBeGreaterThan(0);
    expect(directory.discovery.status).toBe('ready');
  });
});

