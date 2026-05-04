import { describe, expect, it } from 'vitest';
import { buildRuntimeRegistryHealthSnapshot, buildRuntimeRegistrySnapshot } from '@/core/runtime-registry';

describe('runtime registry snapshot', () => {
  it('normalizes operator, skills, MCP, and model state into a single contract', () => {
    const snapshot = buildRuntimeRegistrySnapshot({
      models: [
        { id: 'ollama:llama3.2', name: 'Llama 3.2', provider: 'ollama', type: 'local' },
        { id: 'openai:gpt-4o-mini', name: 'GPT-4o mini', provider: 'openai', type: 'cloud' },
      ],
      operator: {
        status: 'healthy',
        runs: {
          total: 2,
          blocked: 0,
          completed: 2,
          failed: 0,
          byMode: { auto: 0, research: 1, code: 1, cowork: 0 },
          latest: {
            id: 'run_2',
            title: 'Code patch',
            mode: 'code',
            status: 'completed',
            updatedAt: '2026-04-29T10:00:00.000Z',
            reasoningDepth: 'deep',
            approvalCount: 1,
            pendingApprovals: 0,
          },
        },
        approvals: {
          total: 1,
          pending: 0,
          approved: 1,
          rejected: 0,
          expired: 0,
          latest: {
            id: 'appr_1',
            title: 'Approve patch',
            status: 'approved',
            approvalLevel: 'CONFIRM',
            riskLevel: 'write_safe',
            requestedAt: '2026-04-29T09:55:00.000Z',
          },
        },
        summary: '2 runs · 0 pending approvals',
      },
      capabilities: {
        summary: {
          skillCount: 3,
          enabledSkillCount: 3,
          builtInSkillCount: 3,
          enabledBuiltInSkillCount: 3,
          installedSkillCount: 2,
          localOnlySkillCount: 1,
          workspaceScopedSkillCount: 2,
          hostedAllowedSkillCount: 1,
          mcpServerCount: 1,
          mcpConfiguredServerCount: 1,
          mcpEnabledServerCount: 1,
          mcpDisabledServerCount: 0,
          mcpReachableServerCount: 1,
          mcpDegradedServerCount: 0,
          mcpBlockedServerCount: 0,
          mcpDisabledToolCount: 0,
          mcpToolCount: 3,
          mcpResourceCount: 2,
          mcpPromptCount: 1,
          mcpConfigurationStatus: 'ready',
          mcpConfigurationError: undefined,
          approvalLevelCounts: { AUTO: 1, CONFIRM: 1, SCREEN: 1, TWO_FA: 0 },
          riskLevelCounts: { low: 1, medium: 1, high: 1, critical: 0 },
          agenticTechniqueCount: 6,
          agenticTechniqueCategoryCounts: {
            writing_content: 2,
            visual_infographic: 1,
            research_analysis: 1,
            video_content: 1,
            coding_automation: 1,
          },
        },
        skills: {
          builtIn: [
            {
              id: 'research_companion',
              title: 'Research Companion',
              enabled: true,
              approvalLevel: 'CONFIRM',
              riskLevel: 'medium',
            },
          ],
          summary: {
            builtInSkillCount: 3,
            enabledBuiltInSkillCount: 3,
            installedSkillCount: 2,
            localOnlySkillCount: 1,
            workspaceScopedSkillCount: 2,
            hostedAllowedSkillCount: 1,
            mcpConfiguredServerCount: 1,
            mcpEnabledServerCount: 1,
            mcpDisabledServerCount: 0,
            mcpDisabledToolCount: 0,
            mcpConfigurationStatus: 'ready',
            approvalLevelCounts: { AUTO: 1, CONFIRM: 1, SCREEN: 1, TWO_FA: 0 },
            riskLevelCounts: { read_only: 1, write_safe: 1, write_sensitive: 1, destructive: 0, system_critical: 0 },
            agenticTechniqueCount: 6,
            agenticTechniqueCategoryCounts: {
              writing_content: 2,
              visual_infographic: 1,
              research_analysis: 1,
              video_content: 1,
              coding_automation: 1,
            },
          },
          discovery: { status: 'ready' },
        } as unknown as Parameters<typeof buildRuntimeRegistrySnapshot>[0]['capabilities'],
        mcp: {
          mcpServers: [
            {
              id: 'workspace-mcp',
              enabled: true,
              state: 'configured',
              stateReason: 'Configured and ready.',
            },
          ],
          discovery: { cached: false },
        } as unknown as Parameters<typeof buildRuntimeRegistrySnapshot>[0]['capabilities'],
        mcpStatus: 'ready',
        mcpError: undefined,
        discovery: {
          skills: { status: 'ready' },
          mcp: { status: 'ready', cached: false },
        },
      } as unknown as Parameters<typeof buildRuntimeRegistrySnapshot>[0],
    });

    expect(snapshot.status).toBe('healthy');
    expect(snapshot.summary.runCount).toBe(2);
    expect(snapshot.summary.approvalCount).toBe(1);
    expect(snapshot.summary.skillCount).toBe(3);
    expect(snapshot.summary.modelCount).toBe(2);
    expect(snapshot.summary.mcpLiveServerCount).toBe(1);
    expect(snapshot.runs.latest?.id).toBe('run_2');
    expect(snapshot.approvals.latest?.id).toBe('appr_1');
    expect(snapshot.operator.counts.pendingApprovals).toBe(0);
    expect(snapshot.skills.latest?.title).toBe('Research Companion');
    expect(snapshot.mcp.latest?.id).toBe('workspace-mcp');
    expect(snapshot.ml.latest?.provider).toBe('ollama');
    expect(snapshot.models.latest?.provider).toBe('ollama');

    const health = buildRuntimeRegistryHealthSnapshot(snapshot);
    expect(health.ready).toBe(true);
    expect(health.latest.run?.id).toBe('run_2');
    expect(health.latest.ml?.provider).toBe('ollama');
  });

  it('marks ML unavailable when provider discovery fails', () => {
    const snapshot = buildRuntimeRegistrySnapshot({
      models: [],
      modelError: 'provider offline',
      operator: {
        status: 'healthy',
        runs: {
          total: 0,
          blocked: 0,
          completed: 0,
          failed: 0,
          byMode: { auto: 0, research: 0, code: 0, cowork: 0 },
        },
        approvals: {
          total: 0,
          pending: 0,
          approved: 0,
          rejected: 0,
          expired: 0,
        },
        summary: 'No operator runs recorded yet.',
      },
      capabilities: {
        summary: {
          skillCount: 0,
          enabledSkillCount: 0,
          builtInSkillCount: 0,
          enabledBuiltInSkillCount: 0,
          installedSkillCount: 0,
          localOnlySkillCount: 0,
          workspaceScopedSkillCount: 0,
          hostedAllowedSkillCount: 0,
          mcpServerCount: 0,
          mcpConfiguredServerCount: 0,
          mcpEnabledServerCount: 0,
          mcpDisabledServerCount: 0,
          mcpReachableServerCount: 0,
          mcpDegradedServerCount: 0,
          mcpBlockedServerCount: 0,
          mcpDisabledToolCount: 0,
          mcpToolCount: 0,
          mcpResourceCount: 0,
          mcpPromptCount: 0,
          mcpConfigurationStatus: 'skipped',
          mcpConfigurationError: undefined,
          approvalLevelCounts: { AUTO: 0, CONFIRM: 0, SCREEN: 0, TWO_FA: 0 },
          riskLevelCounts: { low: 0, medium: 0, high: 0, critical: 0 },
          agenticTechniqueCount: 0,
          agenticTechniqueCategoryCounts: {
            writing_content: 0,
            visual_infographic: 0,
            research_analysis: 0,
            video_content: 0,
            coding_automation: 0,
          },
        },
        skills: {
          builtIn: [],
          summary: {
            builtInSkillCount: 0,
            enabledBuiltInSkillCount: 0,
            installedSkillCount: 0,
            localOnlySkillCount: 0,
            workspaceScopedSkillCount: 0,
            hostedAllowedSkillCount: 0,
            mcpConfiguredServerCount: 0,
            mcpEnabledServerCount: 0,
            mcpDisabledServerCount: 0,
            mcpDisabledToolCount: 0,
            mcpConfigurationStatus: 'skipped',
            approvalLevelCounts: { AUTO: 0, CONFIRM: 0, SCREEN: 0, TWO_FA: 0 },
            riskLevelCounts: { read_only: 0, write_safe: 0, write_sensitive: 0, destructive: 0, system_critical: 0 },
            agenticTechniqueCount: 0,
            agenticTechniqueCategoryCounts: {
              writing_content: 0,
              visual_infographic: 0,
              research_analysis: 0,
              video_content: 0,
              coding_automation: 0,
            },
          },
          discovery: { status: 'skipped' },
        } as unknown as Parameters<typeof buildRuntimeRegistrySnapshot>[0]['capabilities'],
        mcp: {
          mcpServers: [],
          discovery: { cached: false },
        } as unknown as Parameters<typeof buildRuntimeRegistrySnapshot>[0]['capabilities'],
        mcpStatus: 'unavailable',
        mcpError: 'MCP unavailable',
        discovery: {
          skills: { status: 'skipped' },
          mcp: { status: 'unavailable', cached: false },
        },
      } as unknown as Parameters<typeof buildRuntimeRegistrySnapshot>[0],
    });

    const health = buildRuntimeRegistryHealthSnapshot(snapshot);

    expect(snapshot.ml.status).toBe('degraded');
    expect(snapshot.ml.enabled).toBe(false);
    expect(snapshot.ml.lastError).toBe('provider offline');
    expect(health.ready).toBe(false);
  });
});
