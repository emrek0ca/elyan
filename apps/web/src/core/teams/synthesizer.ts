import type { ScrapedContent } from '@/types/search';
import type { TeamArtifact, TeamMessage, TeamPlan, TeamRunSummary } from './types';

function findArtifact(artifacts: TeamArtifact[], ids: string[]) {
  return [...artifacts].reverse().find((artifact) => ids.includes(artifact.taskId));
}

function verifierPassed(content: string) {
  return /^pass\b/i.test(content.trim());
}

function summarizeVerifier(content: string) {
  return content.trim().replace(/^(pass|fail)\b[:\s-]*/i, '').trim() || content.trim();
}

export function synthesizeTeamRun(args: {
  teamPlan: TeamPlan;
  artifacts: TeamArtifact[];
  messages: TeamMessage[];
  sources: ScrapedContent[];
  modelId: string;
  modelProvider: string;
  startedAt: string;
}): { text: string; summary: TeamRunSummary } {
  const verifier = findArtifact(args.artifacts, ['verify']);
  const verifierContent = verifier?.content ?? 'FAIL Verification task did not produce an artifact.';
  const passed = verifierPassed(verifierContent);
  const bestOutput =
    findArtifact(args.artifacts, ['review']) ??
    findArtifact(args.artifacts, ['execute']) ??
    findArtifact(args.artifacts, ['research']) ??
    findArtifact(args.artifacts, ['scope']);
  const finishedAt = new Date().toISOString();
  const verifierSummary = summarizeVerifier(verifierContent);
  const sourceLines = args.sources
    .slice(0, 5)
    .map((source, index) => `[${index + 1}] ${source.title || source.url} - ${source.url}`);
  const body = bestOutput?.content.trim() || 'No team artifact was produced.';
  const text = passed
    ? [
        body,
        args.sources.length > 0 ? `\nSources:\n${sourceLines.join('\n')}` : '',
        `\nTeam run: ${args.teamPlan.runId}`,
      ].filter(Boolean).join('\n')
    : [
        `Verification failed: ${verifierSummary}`,
        '',
        'The team run did not pass final verification, so this should be treated as a draft.',
        '',
        body,
        `\nTeam run: ${args.teamPlan.runId}`,
      ].join('\n');

  return {
    text,
    summary: {
      runId: args.teamPlan.runId,
      status: passed ? 'completed' : 'failed',
      createdAt: args.startedAt,
      finishedAt,
      query: args.teamPlan.query,
      mode: args.teamPlan.mode,
      modelId: args.modelId,
      modelProvider: args.modelProvider,
      taskCount: args.teamPlan.tasks.length,
      agentCount: args.teamPlan.agents.length,
      verifier: {
        passed,
        summary: verifierSummary,
      },
      finalText: text,
      artifactCount: args.artifacts.length,
      sourceCount: args.sources.length,
    },
  };
}
