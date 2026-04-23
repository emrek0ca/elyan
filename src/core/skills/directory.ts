import { buildBuiltinSkillCatalog } from './catalog';
import { readSkillInstallations } from './lock';
import type { SkillDirectorySnapshot } from './types';

export async function buildSkillDirectorySnapshot(includeInstalled = true): Promise<SkillDirectorySnapshot> {
  const builtIn = buildBuiltinSkillCatalog();
  const installedResult = includeInstalled ? await readSkillInstallations() : { installed: [], discovery: { attempted: false, status: 'skipped' as const } };

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
        when: 'The task needs a connected app, prompt, resource, or tool from an external server.',
        why: 'MCP surfaces stay explicit and policy-bound instead of becoming hidden side effects.',
      },
      {
        kind: 'calculation',
        title: 'Deterministic math',
        when: 'The request is numeric, formulaic, or otherwise deterministic.',
        why: 'Use the smallest local arithmetic path before broader reasoning.',
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

