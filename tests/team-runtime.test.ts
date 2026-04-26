import { mkdtemp, readFile, rm } from 'fs/promises';
import { join } from 'path';
import { tmpdir } from 'os';
import { afterEach, describe, expect, it } from 'vitest';
import { buildOrchestrationPlan } from '@/core/orchestration';
import { buildTeamPlan, __teamPlannerTestHooks, TeamRunStore, TeamRunner, type TeamAgentExecutor } from '@/core/teams';

describe('Team runtime', () => {
  const tempDirs: string[] = [];

  afterEach(async () => {
    while (tempDirs.length > 0) {
      const dir = tempDirs.pop();
      if (dir) {
        await rm(dir, { recursive: true, force: true });
      }
    }
  });

  async function createStore() {
    const dir = await mkdtemp(join(tmpdir(), 'elyan-team-'));
    tempDirs.push(dir);
    return new TeamRunStore(dir);
  }

  it('builds a bounded local-first team plan for complex work', () => {
    const sourcePlan = buildOrchestrationPlan(
      'Research Elyan agent routing, plan the implementation, review the risks, and verify the result before final answer.',
      'research'
    );
    const teamPlan = buildTeamPlan({
      query: 'Research Elyan agent routing, plan the implementation, review the risks, and verify the result before final answer.',
      mode: 'research',
      sourcePlan,
      maxConcurrentAgents: 2,
      maxTasksPerRun: 6,
      allowCloudEscalation: false,
    });

    expect(sourcePlan.executionMode).toBe('team');
    expect(teamPlan.modelRoutingMode).toBe('local_first');
    expect(teamPlan.tasks.length).toBeLessThanOrEqual(6);
    expect(teamPlan.tasks.at(-1)?.assignedRole).toBe('verifier');
    expect(teamPlan.agents.some((agent) => agent.role === 'researcher')).toBe(true);
  });

  it('rejects cyclic task graphs', () => {
    expect(() =>
      __teamPlannerTestHooks.validateTaskGraph([
        {
          id: 'a',
          title: 'A',
          summary: 'A',
          kind: 'analysis',
          assignedRole: 'planner',
          dependsOn: ['b'],
          requiresConfirmation: false,
          status: 'pending',
        },
        {
          id: 'b',
          title: 'B',
          summary: 'B',
          kind: 'review',
          assignedRole: 'reviewer',
          dependsOn: ['a'],
          requiresConfirmation: false,
          status: 'pending',
        },
      ])
    ).toThrow(/cycle/);
  });

  it('persists team events, artifacts, and summary without requiring a live model', async () => {
    const store = await createStore();
    const sourcePlan = buildOrchestrationPlan(
      'Research the implementation, produce a reviewed answer, and verify it.',
      'research'
    );
    const executor: TeamAgentExecutor = async ({ task }) =>
      task.kind === 'verification' ? 'PASS Output is bounded and verified.' : `${task.title} artifact`;
    const runner = new TeamRunner(
      store,
      executor,
      async () => ({ modelId: 'ollama:test-local', providerId: 'ollama' })
    );

    const result = await runner.run({
      query: 'Research the implementation, produce a reviewed answer, and verify it.',
      mode: 'research',
      sourcePlan,
      maxConcurrentAgents: 2,
      maxTasksPerRun: 6,
      allowCloudEscalation: false,
      searchEnabled: false,
    });

    const runDir = store.getRunDir(result.teamPlan.runId);
    const events = await readFile(join(runDir, 'events.jsonl'), 'utf8');
    const artifacts = JSON.parse(await readFile(join(runDir, 'artifacts.json'), 'utf8')) as unknown[];
    const summary = JSON.parse(await readFile(join(runDir, 'summary.json'), 'utf8')) as { verifier: { passed: boolean } };

    expect(result.summary.verifier.passed).toBe(true);
    expect(events).toContain('run_completed');
    expect(artifacts.length).toBe(result.teamPlan.tasks.length);
    expect(summary.verifier.passed).toBe(true);
  });

  it('blocks confirmation-required task execution', async () => {
    const store = await createStore();
    const sourcePlan = buildOrchestrationPlan(
      'Open https://example.com, click the button, submit the form, then verify the action.',
      'speed'
    );
    const runner = new TeamRunner(
      store,
      async ({ task }) => (task.kind === 'verification' ? 'PASS verified' : `${task.title} artifact`),
      async () => ({ modelId: 'ollama:test-local', providerId: 'ollama' })
    );

    const result = await runner.run({
      query: 'Open https://example.com, click the button, submit the form, then verify the action.',
      mode: 'speed',
      sourcePlan,
      maxConcurrentAgents: 2,
      maxTasksPerRun: 6,
      allowCloudEscalation: false,
      searchEnabled: false,
    });

    expect(result.summary.status).toBe('failed');
    expect(result.text).toContain('Verification failed');
  });
});
