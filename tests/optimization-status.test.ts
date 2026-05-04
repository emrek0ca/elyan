import { describe, expect, it } from 'vitest';
import { buildOptimizationStatusSnapshot } from '@/core/optimization/status';

function createSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    capabilities: [
      {
        id: 'optimization_solve',
        title: 'Optimization Solve',
        description: 'Models assignment and resource allocation problems as QUBO.',
        library: 'elyan-optimization',
        timeoutMs: 3000,
        enabled: true,
        source: 'local_module',
        profile: {
          category: 'optimization',
          riskLevel: 'low',
          approvalLevel: 'AUTO',
          verificationMode: 'schema',
          rollbackMode: 'none',
          safeByDefault: true,
          useCases: [],
        },
      },
    ],
    local: {
      capabilities: [],
      bridgeTools: [
        {
          id: 'optimization_solve',
          title: 'Optimization Solve',
          description: 'Models assignment and resource allocation problems as QUBO.',
          library: 'elyan-optimization',
          timeoutMs: 3000,
          enabled: true,
        },
      ],
    },
    skills: {
      builtIn: [
        {
          id: 'optimization_decision',
          title: 'Optimization Decision',
          version: '1.0.0',
          description: 'Optimization decision skill.',
          domain: 'optimization',
          enabled: true,
          source: { kind: 'builtin' },
          triggers: {
            keywords: [],
            intents: ['procedural'],
            urlSensitive: false,
            documentSensitive: false,
            mcpSensitive: false,
            actionSensitive: false,
          },
          preferredCapabilityIds: [],
          policyBoundary: 'local',
          localOnly: true,
          sharedAllowed: false,
          hostedAllowed: false,
          externalActionsAllowed: false,
          auditMode: 'summary',
          riskLevel: 'read_only',
          approvalLevel: 'AUTO',
          outputShape: 'report',
        },
      ],
      installed: [],
      discovery: {
        attempted: false,
        status: 'skipped',
      },
      summary: {
        builtInSkillCount: 1,
        enabledBuiltInSkillCount: 1,
        installedSkillCount: 0,
        localOnlySkillCount: 1,
        workspaceScopedSkillCount: 0,
        hostedAllowedSkillCount: 0,
        mcpConfiguredServerCount: 0,
        mcpEnabledServerCount: 0,
        mcpDisabledServerCount: 0,
        mcpDisabledToolCount: 0,
        mcpConfigurationStatus: 'skipped',
        approvalLevelCounts: {
          AUTO: 1,
          CONFIRM: 0,
          SCREEN: 0,
          TWO_FA: 0,
        },
        riskLevelCounts: {
          read_only: 1,
          write_safe: 0,
          write_sensitive: 0,
          destructive: 0,
          system_critical: 0,
        },
        agenticTechniqueCount: 0,
        agenticTechniqueCategoryCounts: {
          writing_content: 0,
          visual_infographic: 0,
          research_analysis: 0,
          video_content: 0,
          coding_automation: 0,
        },
      },
      selectionGuide: [],
    },
    ...overrides,
  } as never;
}

describe('optimization status snapshot', () => {
  it('reports a ready optimization lane only when capability, bridge tool, and skill are all enabled', () => {
    const readySnapshot = buildOptimizationStatusSnapshot(createSnapshot());

    expect(readySnapshot.ready).toBe(true);
    expect(readySnapshot.summary).toContain('Optimization lane is ready');
    expect(readySnapshot.guidance[0]).toContain('classical and quantum-inspired');

    const partialSnapshot = buildOptimizationStatusSnapshot(
      createSnapshot({
        capabilities: [],
        local: {
          capabilities: [],
          bridgeTools: [],
        },
        skills: {
          builtIn: [],
        },
      })
    );

    expect(partialSnapshot.ready).toBe(false);
    expect(partialSnapshot.summary).toContain('missing capability, bridge tool, skill');
  });
});
