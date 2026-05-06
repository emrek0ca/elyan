import { normalizeEnvValue } from '@/lib/env-values';

export type StartupEnvIssue = {
  key: string;
  message: string;
};

export type StartupValidationResult =
  | {
      ok: true;
      issues: [];
    }
  | {
      ok: false;
      issues: StartupEnvIssue[];
    };

export type StartupEvaluationReport = {
  runAt: string;
  regressions: number;
  failures: number;
  averageOverallScore: number;
  passRate: number;
};

function readEnvValue(source: NodeJS.ProcessEnv, key: string) {
  return normalizeEnvValue(source[key]);
}

function hasAnyModelProvider(source: NodeJS.ProcessEnv) {
  return Boolean(
    readEnvValue(source, 'OLLAMA_URL') ||
      readEnvValue(source, 'OPENAI_API_KEY') ||
      readEnvValue(source, 'ANTHROPIC_API_KEY') ||
      readEnvValue(source, 'GROQ_API_KEY')
  );
}

export function validateStartupEnvironment(source: NodeJS.ProcessEnv = process.env): StartupValidationResult {
  const issues: StartupEnvIssue[] = [];

  if (!readEnvValue(source, 'DATABASE_URL')) {
    issues.push({
      key: 'DATABASE_URL',
      message: 'DATABASE_URL must point to the local or hosted PostgreSQL database.',
    });
  }

  if (!readEnvValue(source, 'NEXTAUTH_URL')) {
    issues.push({
      key: 'NEXTAUTH_URL',
      message: 'NEXTAUTH_URL is required so auth callbacks and cookies resolve correctly.',
    });
  }

  if (!readEnvValue(source, 'NEXTAUTH_SECRET') && !readEnvValue(source, 'AUTH_SECRET')) {
    issues.push({
      key: 'NEXTAUTH_SECRET',
      message: 'Set NEXTAUTH_SECRET or AUTH_SECRET to enable hosted auth and signed sessions.',
    });
  }

  if (!readEnvValue(source, 'SEARXNG_URL')) {
    issues.push({
      key: 'SEARXNG_URL',
      message: 'SEARXNG_URL is required for the web retrieval/search API base.',
    });
  }

  if (!readEnvValue(source, 'OLLAMA_URL')) {
    issues.push({
      key: 'OLLAMA_URL',
      message: 'OLLAMA_URL is required so the local model backend has a configured API base.',
    });
  }

  if (!hasAnyModelProvider(source)) {
    issues.push({
      key: 'MODEL_PROVIDER',
      message: 'Configure at least one model provider: OLLAMA_URL, OPENAI_API_KEY, ANTHROPIC_API_KEY, or GROQ_API_KEY.',
    });
  }

  if (issues.length > 0) {
    return {
      ok: false,
      issues,
    };
  }

  return {
    ok: true,
    issues: [],
  };
}

function round4(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(4)) : 0;
}

export async function runStartupEvaluationCheck(timeoutMs = 45_000): Promise<StartupEvaluationReport | null> {
  if (process.env.NODE_ENV === 'test') {
    return null;
  }

  try {
    const { runScenarioSuite } = await import('@/core/testing/eval-runner');
    let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timeoutHandle = setTimeout(() => {
        reject(new Error('startup evaluation check timed out'));
      }, timeoutMs);
    });

    const report = (await Promise.race([runScenarioSuite(), timeout])) as Awaited<
      ReturnType<typeof runScenarioSuite>
    >;
    if (timeoutHandle) {
      clearTimeout(timeoutHandle);
    }
    const passRate = report.summary.runCount > 0 ? report.summary.passCount / report.summary.runCount : 0;
    const averageOverallScore = report.summary.averageScores.overall;
    const regressions = report.summary.failureCount;

    return {
      runAt: report.runAt,
      regressions,
      failures: report.summary.failureCount,
      averageOverallScore: round4(averageOverallScore),
      passRate: round4(passRate),
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : 'startup evaluation check failed';
    console.warn('[elyan] startup evaluation warning', message);
    return null;
  }
}
