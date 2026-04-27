import { buildBuiltinSkillCatalog } from './catalog';
import { readSkillInstallations } from './lock';
import type { SkillApprovalLevel, SkillDirectorySnapshot, SkillRiskLevel, SkillTechniqueCategory } from './types';
import { readMcpConfigurationSnapshot } from '@/core/mcp';

const skillApprovalLevels: SkillApprovalLevel[] = ['AUTO', 'CONFIRM', 'SCREEN', 'TWO_FA'];
const skillRiskLevels: SkillRiskLevel[] = ['read_only', 'write_safe', 'write_sensitive', 'destructive', 'system_critical'];
const skillTechniqueCategories: SkillTechniqueCategory[] = [
  'writing_content',
  'visual_infographic',
  'research_analysis',
  'video_content',
  'coding_automation',
];

function countSkillApprovals(skills: ReturnType<typeof buildBuiltinSkillCatalog>): Record<SkillApprovalLevel, number> {
  return Object.fromEntries(
    skillApprovalLevels.map((level) => [level, skills.filter((skill) => skill.approvalLevel === level).length])
  ) as Record<SkillApprovalLevel, number>;
}

function countSkillRiskLevels(skills: ReturnType<typeof buildBuiltinSkillCatalog>): Record<SkillRiskLevel, number> {
  return Object.fromEntries(
    skillRiskLevels.map((level) => [level, skills.filter((skill) => skill.riskLevel === level).length])
  ) as Record<SkillRiskLevel, number>;
}

function countSkillTechniques(skills: ReturnType<typeof buildBuiltinSkillCatalog>): Record<SkillTechniqueCategory, number> {
  return Object.fromEntries(
    skillTechniqueCategories.map((category) => [
      category,
      skills.reduce(
        (total, skill) => total + skill.techniques.filter((technique) => technique.category === category).length,
        0
      ),
    ])
  ) as Record<SkillTechniqueCategory, number>;
}

export async function buildSkillDirectorySnapshot(includeInstalled = true): Promise<SkillDirectorySnapshot> {
  const builtIn = buildBuiltinSkillCatalog();
  const installedResult = includeInstalled ? await readSkillInstallations() : { installed: [], discovery: { attempted: false, status: 'skipped' as const } };
  const mcpConfiguration = readMcpConfigurationSnapshot();

  return {
    builtIn,
    installed: installedResult.installed,
    discovery: installedResult.discovery,
    summary: {
      builtInSkillCount: builtIn.length,
      enabledBuiltInSkillCount: builtIn.filter((skill) => skill.enabled).length,
      installedSkillCount: installedResult.installed.length,
      localOnlySkillCount: builtIn.filter((skill) => skill.localOnly).length,
      workspaceScopedSkillCount: builtIn.filter((skill) => skill.policyBoundary === 'workspace').length,
      hostedAllowedSkillCount: builtIn.filter((skill) => skill.hostedAllowed).length,
      mcpConfiguredServerCount: mcpConfiguration.serverCount,
      mcpEnabledServerCount: mcpConfiguration.enabledServerCount,
      mcpDisabledServerCount: mcpConfiguration.disabledServerCount,
      mcpDisabledToolCount: mcpConfiguration.disabledToolCount,
      mcpConfigurationStatus: mcpConfiguration.status,
      mcpConfigurationError: mcpConfiguration.error,
      approvalLevelCounts: countSkillApprovals(builtIn),
      riskLevelCounts: countSkillRiskLevels(builtIn),
      agenticTechniqueCount: builtIn.reduce((total, skill) => total + skill.techniques.length, 0),
      agenticTechniqueCategoryCounts: countSkillTechniques(builtIn),
    },
    selectionGuide: [
      {
        kind: 'research',
        title: 'Research skill pack',
        when: 'The answer needs external evidence, source clustering, or citation-heavy synthesis.',
        why: 'Keeps research explicit and biased toward the strongest evidence path.',
      },
      {
        kind: 'operator',
        title: 'Workspace operator',
        when: 'The task touches local files, private workspace state, or deterministic local actions.',
        why: 'Keeps private context local and prefers bounded actions over broad reasoning.',
      },
      {
        kind: 'documents',
        title: 'Document inspector',
        when: 'The task starts with PDFs, DOCX files, spreadsheets, or tables.',
        why: 'Document extraction should stay structured and predictable.',
      },
      {
        kind: 'browser',
        title: 'Browser operator',
        when: 'The task needs rendered page inspection or a short, explicit browser interaction.',
        why: 'Browser work should be visible, bounded, and easy to audit.',
      },
      {
        kind: 'mcp',
        title: 'MCP connector',
        when:
          mcpConfiguration.configured
            ? `The task needs a connected app, prompt, resource, or tool from one of the ${mcpConfiguration.serverCount} configured MCP servers.`
            : 'The task needs a connected app, prompt, resource, or tool, and MCP servers are not configured yet.',
        why: mcpConfiguration.configured
          ? 'MCP surfaces stay explicit and policy-bound instead of becoming hidden side effects.'
          : 'Keep the path visible and fall back to local skills until an MCP surface is configured.',
      },
      {
        kind: 'calculation',
        title: 'Deterministic math',
        when: 'The request is numeric, formulaic, or otherwise deterministic.',
        why: 'Use the smallest local arithmetic path before broader reasoning.',
      },
      {
        kind: 'optimization',
        title: 'Optimization decision',
        when: 'The request involves assignment, routing, scheduling, load balancing, resource allocation, QUBO, Ising, or minimum-cost decisions.',
        why: 'Convert the problem into an explicit model, compare solvers, and return an auditable decision report.',
      },
      {
        kind: 'general',
        title: 'General answer',
        when: 'No specialized skill provides a stronger path.',
        why: 'Keep the fallback path clean when no capability improves the result.',
      },
    ],
  };
}
