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

  it('selects SCQA as a document technique without changing the policy boundary', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Write this using SCQA with situation, complication, question, and answer sections',
      mode: 'speed',
      taskIntent: 'procedural',
    });

    expect(decision.selectedSkillId).toBe('document_inspector');
    expect(decision.policyBoundary).toBe('local');
    expect(decision.selectedTechniques.map((technique) => technique.id)).toContain('scqa-writing-framework');
  });

  it('routes prototype and UI direction work to the design producer skill', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Create a premium UI prototype and redesign direction for the command center',
      mode: 'speed',
      taskIntent: 'procedural',
    });

    expect(decision.selectedSkillId).toBe('design_producer');
    expect(decision.resultShape).toBe('artifact');
    expect(decision.requiresConfirmation).toBe(true);
    expect(decision.preferredCapabilityIds).toEqual(expect.arrayContaining(['web_read_dynamic', 'markdown_render']));
  });

  it('keeps visual diagram requests on design producer techniques', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Create a flowchart decision tree for this onboarding process',
      mode: 'speed',
      taskIntent: 'procedural',
    });

    expect(decision.selectedSkillId).toBe('design_producer');
    expect(decision.selectedTechniques.map((technique) => technique.id)).toContain('flowchart-decision-builder');
  });

  it('routes source validation to the research companion technique pack', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Validate these sources for credibility, reliability, and bias',
      mode: 'research',
      taskIntent: 'research',
    });

    expect(decision.selectedSkillId).toBe('research_companion');
    expect(decision.selectedTechniques.map((technique) => technique.id)).toContain('source-validation-skill');
  });

  it('routes code review requests to the workspace operator technique pack', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Review this code for bugs, regressions, and missing tests',
      mode: 'speed',
      taskIntent: 'procedural',
    });

    expect(decision.selectedSkillId).toBe('workspace_operator');
    expect(decision.selectedTechniques.map((technique) => technique.id)).toContain('code-review-skill');
  });

  it('routes optimization requests to the optimization decision technique pack', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Find the best distribution of tasks and resources and compare the solver results',
      mode: 'speed',
      taskIntent: 'procedural',
    });

    expect(decision.selectedSkillId).toBe('optimization_decision');
    expect(decision.selectedTechniques.map((technique) => technique.id)).toEqual(
      expect.arrayContaining([
        'optimization-modeling-playbook',
        'optimization-solver-comparator',
        'optimization-decision-reporter',
      ])
    );
  });

  it('keeps video script requests on the general answer technique path', () => {
    const decision = buildSkillExecutionDecision({
      query: 'Make a video script with a strong hook and tight pacing',
      mode: 'speed',
      taskIntent: 'direct_answer',
    });

    expect(decision.selectedSkillId).toBe('general_answer');
    expect(decision.selectedTechniques.map((technique) => technique.id)).toContain('video-script-generator');
  });

  it('reads installed skill lock records when building the skill directory', async () => {
    const directory = await buildSkillDirectorySnapshot(true);

    expect(directory.builtIn.length).toBeGreaterThan(0);
    expect(directory.summary.enabledBuiltInSkillCount).toBeGreaterThan(0);
    expect(directory.summary.installedSkillCount).toBeGreaterThan(0);
    expect(directory.summary.agenticTechniqueCount).toBe(25);
    expect(directory.summary.agenticTechniqueCategoryCounts.writing_content).toBe(7);
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
      description: 'A legacy built-in skill without v1.3 operational metadata.',
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
    expect(manifest.techniques).toEqual([]);
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
