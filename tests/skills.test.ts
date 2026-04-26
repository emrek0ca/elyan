import { describe, expect, it } from 'vitest';
import { buildSkillDirectorySnapshot, buildSkillExecutionDecision } from '@/core/skills';
import { skillManifestSchema } from '@/core/skills/types';

function restoreEnvValue(key: string, value: string | undefined) {
  if (value === undefined) {
    delete process.env[key];
    return;
  }

  process.env[key] = value;
}

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

  it('biases code and repo work toward the workspace operator skill', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Refactor the repo and update tests for the code path',
      mode: 'speed',
      taskIntent: 'procedural',
    });

    expect(decision.selectedSkillId).toBe('workspace_operator');
    expect(decision.resultShape).toBe('artifact');
  });

  it('biases document drafting toward the document inspector skill', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Draft a design brief in markdown and export the document as docx',
      mode: 'speed',
      taskIntent: 'procedural',
    });

    expect(decision.selectedSkillId).toBe('document_inspector');
    expect(decision.resultShape).toBe('report');
  });

  it('reads installed skill lock records when building the skill directory', async () => {
    const directory = await buildSkillDirectorySnapshot(true);

    expect(directory.builtIn.length).toBeGreaterThan(0);
    expect(directory.summary.enabledBuiltInSkillCount).toBeGreaterThan(0);
    expect(directory.summary.installedSkillCount).toBeGreaterThan(0);
    expect(directory.discovery.status).toBe('ready');
  });

  it('reflects configured MCP surfaces in the skill directory and selection notes', async () => {
    const previous = process.env.ELYAN_MCP_SERVERS;
    process.env.ELYAN_MCP_SERVERS = JSON.stringify({
      servers: [
        {
          id: 'workspace-mcp',
          transport: 'stdio',
          command: 'node',
          args: [],
        },
      ],
    });

    try {
      const directory = await buildSkillDirectorySnapshot(true);
      const decision = buildSkillExecutionDecision({
        query: 'Connect Gmail and calendar integrations through MCP',
        mode: 'speed',
        taskIntent: 'personal_workflow',
      });

      expect(directory.summary.mcpConfiguredServerCount).toBe(1);
      expect(directory.summary.mcpConfigurationStatus).toBe('ready');
      expect(decision.selectedSkillId).toBe('mcp_connector');
      expect(decision.candidates.find((candidate) => candidate.skillId === 'mcp_connector')?.reason).toContain(
        'configured MCP servers: 1'
      );
    } finally {
      restoreEnvValue('ELYAN_MCP_SERVERS', previous);
    }
  });

  it('keeps new skill operational metadata backward compatible', () => {
    const manifest = skillManifestSchema.parse({
      id: 'legacy_builtin',
      title: 'Legacy Builtin',
      version: '1.0.0',
      description: 'A legacy built-in skill without v1.2 operational metadata.',
      domain: 'general',
      enabled: true,
      source: {
        kind: 'builtin',
      },
      triggers: {
        keywords: [],
        intents: ['direct_answer'],
        urlSensitive: false,
        documentSensitive: false,
        mcpSensitive: false,
        actionSensitive: false,
      },
      preferredCapabilityIds: [],
      policyBoundary: 'local',
      localOnly: true,
      sharedAllowed: true,
      hostedAllowed: true,
      externalActionsAllowed: false,
      auditMode: 'summary',
      outputShape: 'answer',
    });

    expect(manifest.riskLevel).toBe('read_only');
    expect(manifest.approvalLevel).toBe('AUTO');
    expect(manifest.inputContract.summary).toContain('Natural-language');
    expect(manifest.outputContract.summary).toContain('Auditable');
    expect(manifest.verificationMode).toBe('summary');
  });

  it('summarizes MCP disabled surfaces and skill approval/risk metadata', async () => {
    const previousServers = process.env.ELYAN_MCP_SERVERS;
    const previousDisabledServers = process.env.ELYAN_DISABLED_MCP_SERVERS;
    const previousDisabledTools = process.env.ELYAN_DISABLED_MCP_TOOLS;
    process.env.ELYAN_MCP_SERVERS = JSON.stringify({
      servers: [
        {
          id: 'workspace-mcp',
          transport: 'stdio',
          command: 'node',
          args: [],
        },
      ],
    });
    process.env.ELYAN_DISABLED_MCP_SERVERS = 'workspace-mcp';
    process.env.ELYAN_DISABLED_MCP_TOOLS = 'delete_file';

    try {
      const directory = await buildSkillDirectorySnapshot(true);

      expect(directory.summary.mcpConfiguredServerCount).toBe(1);
      expect(directory.summary.mcpEnabledServerCount).toBe(0);
      expect(directory.summary.mcpDisabledServerCount).toBe(1);
      expect(directory.summary.mcpDisabledToolCount).toBe(1);
      expect(directory.summary.approvalLevelCounts.CONFIRM).toBeGreaterThan(0);
      expect(directory.summary.riskLevelCounts.write_safe).toBeGreaterThan(0);
    } finally {
      restoreEnvValue('ELYAN_MCP_SERVERS', previousServers);
      restoreEnvValue('ELYAN_DISABLED_MCP_SERVERS', previousDisabledServers);
      restoreEnvValue('ELYAN_DISABLED_MCP_TOOLS', previousDisabledTools);
    }
  });
});
