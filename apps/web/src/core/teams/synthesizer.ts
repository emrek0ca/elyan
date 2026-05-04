import type { ScrapedContent } from '@/types/search';
import type { TeamArtifact, TeamMessage, TeamPlan, TeamRunSummary, TeamVerification } from './types';

function findArtifact(artifacts: TeamArtifact[], ids: string[]) {
  return [...artifacts].reverse().find((artifact) => ids.includes(artifact.taskId));
}

function findVerificationArtifact(artifacts: TeamArtifact[]) {
  return [...artifacts].reverse().find((artifact) => artifact.kind === 'verification');
}

function summarizeVerifier(content: string) {
  return content.trim().replace(/^(pass|fail)\b[:\s-]*/i, '').trim() || content.trim();
}

function buildDraftNotice(verifier: TeamVerification) {
  switch (verifier.state) {
    case 'passed':
      return '';
    case 'failed':
      return 'Team run is a draft because final verification failed.';
    case 'missing_artifact':
      return 'Team run is a draft because final verification was not produced.';
    case 'unstructured':
      return 'Team run is a draft because final verification was unstructured.';
    case 'error':
      return 'Team run is a draft because final verification errored.';
    default:
      return 'Team run is a draft because final verification is unavailable.';
  }
}

function normalizeVerification(artifact?: TeamArtifact | null): TeamVerification {
  const metadata = artifact?.metadata as { verification?: TeamVerification } | undefined;
  const verification = metadata?.verification;

  if (verification?.summary && typeof verification.passed === 'boolean') {
    return verification;
  }

  if (!artifact) {
    return {
      passed: false,
      summary: 'Verification task did not produce a structured result.',
      state: 'missing_artifact',
    };
  }

  const content = artifact.content.trim();
  if (/^(pass|fail)\b/i.test(content)) {
    const passed = /^pass\b/i.test(content);
    const summary = summarizeVerifier(content) || (passed ? 'Verification passed.' : 'Verification failed.');

    return {
      passed,
      summary,
      state: passed ? 'passed' : 'failed',
      artifactId: artifact.id,
      rawContent: content,
    };
  }

  return {
    passed: false,
    summary: 'Verification output was not structured.',
    state: 'unstructured',
    artifactId: artifact.id,
    rawContent: content || undefined,
  };
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
  const verifierArtifact = findVerificationArtifact(args.artifacts);
  const verifier = normalizeVerification(verifierArtifact);
  const bestOutput =
    findArtifact(args.artifacts, ['review']) ??
    findArtifact(args.artifacts, ['execute']) ??
    findArtifact(args.artifacts, ['research']) ??
    findArtifact(args.artifacts, ['scope']);
  const finishedAt = new Date().toISOString();
  const verifierSummary = verifier.summary;
  const sourceLines = args.sources
    .slice(0, 5)
    .map((source, index) => `[${index + 1}] ${source.title || source.url} - ${source.url}`);
  const body = bestOutput?.content.trim() || 'No team artifact was produced.';
  const draftNotice = buildDraftNotice(verifier);
  const text = verifier.passed
    ? [
        body,
        args.sources.length > 0 ? `\nSources:\n${sourceLines.join('\n')}` : '',
        `\nTeam run: ${args.teamPlan.runId}`,
      ].filter(Boolean).join('\n')
    : [
        draftNotice || 'Team run is a draft.',
        '',
        body,
        `\nTeam run: ${args.teamPlan.runId}`,
      ].join('\n');

  return {
    text,
    summary: {
      runId: args.teamPlan.runId,
      status: verifier.passed ? 'completed' : 'failed',
      createdAt: args.startedAt,
      finishedAt,
      query: args.teamPlan.query,
      mode: args.teamPlan.mode,
      modelId: args.modelId,
      modelProvider: args.modelProvider,
      taskCount: args.teamPlan.tasks.length,
      agentCount: args.teamPlan.agents.length,
      verifier: {
        passed: verifier.passed,
        summary: verifierSummary,
        state: verifier.state,
        artifactId: verifier.artifactId,
      },
      finalText: text,
      artifactCount: args.artifacts.length,
      sourceCount: args.sources.length,
    },
  };
}
