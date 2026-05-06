type StartupEnvIssue = {
  key: string;
  message: string;
};

function readEnvValue(key: string) {
  const value = process.env[key]?.trim();
  if (!value || value.startsWith('<')) {
    return undefined;
  }
  return value;
}

function hasAnyModelProvider() {
  return Boolean(
    readEnvValue('OLLAMA_URL') ||
      readEnvValue('OPENAI_API_KEY') ||
      readEnvValue('ANTHROPIC_API_KEY') ||
      readEnvValue('GROQ_API_KEY')
  );
}

function validateStartupEnvironment() {
  const issues: StartupEnvIssue[] = [];

  if (!readEnvValue('DATABASE_URL')) {
    issues.push({
      key: 'DATABASE_URL',
      message: 'DATABASE_URL must point to the local or hosted PostgreSQL database.',
    });
  }

  if (!readEnvValue('NEXTAUTH_URL')) {
    issues.push({
      key: 'NEXTAUTH_URL',
      message: 'NEXTAUTH_URL is required so auth callbacks and cookies resolve correctly.',
    });
  }

  if (!readEnvValue('NEXTAUTH_SECRET') && !readEnvValue('AUTH_SECRET')) {
    issues.push({
      key: 'NEXTAUTH_SECRET',
      message: 'Set NEXTAUTH_SECRET or AUTH_SECRET to enable hosted auth and signed sessions.',
    });
  }

  if (!readEnvValue('SEARXNG_URL')) {
    issues.push({
      key: 'SEARXNG_URL',
      message: 'SEARXNG_URL is required for the web retrieval/search API base.',
    });
  }

  if (!readEnvValue('OLLAMA_URL')) {
    issues.push({
      key: 'OLLAMA_URL',
      message: 'OLLAMA_URL is required so the local model backend has a configured API base.',
    });
  }

  if (!hasAnyModelProvider()) {
    issues.push({
      key: 'MODEL_PROVIDER',
      message: 'Configure at least one model provider: OLLAMA_URL, OPENAI_API_KEY, ANTHROPIC_API_KEY, or GROQ_API_KEY.',
    });
  }

  return issues;
}

export async function register() {
  const issues = validateStartupEnvironment();

  if (issues.length > 0) {
    const details = issues.map((issue) => `${issue.key}: ${issue.message}`).join(' | ');
    throw new Error(`Elyan startup validation failed: ${details}`);
  }
}
