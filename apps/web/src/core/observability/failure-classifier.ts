export type ObservabilityFailureType = 'LLM_ERROR' | 'TOOL_ERROR' | 'TIMEOUT' | 'EMPTY_OUTPUT' | 'BAD_RESULT';

export type FailureClassification = {
  errorType: ObservabilityFailureType;
  reason: string;
};

export type FailureClassificationInput = {
  error?: unknown;
  outputText?: string;
  failureReason?: string;
  tool?: string;
  verdict?: 'success' | 'retry' | 'failure';
  modelId?: string;
  modelProvider?: string;
  sourcesCount?: number;
};

function normalizeText(value: string) {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function readErrorText(error: unknown) {
  if (!error) {
    return '';
  }

  if (typeof error === 'string') {
    return error;
  }

  if (error instanceof Error) {
    return [error.name, error.message, error.stack].filter(Boolean).join(' ');
  }

  if (typeof error === 'object') {
    const candidate = error as Record<string, unknown>;
    return [
      typeof candidate.name === 'string' ? candidate.name : '',
      typeof candidate.message === 'string' ? candidate.message : '',
      typeof candidate.code === 'string' ? candidate.code : '',
      typeof candidate.reason === 'string' ? candidate.reason : '',
    ]
      .filter(Boolean)
      .join(' ');
  }

  return String(error);
}

function hasAny(text: string, patterns: RegExp[]) {
  return patterns.some((pattern) => pattern.test(text));
}

function buildReason(source: string, label: ObservabilityFailureType) {
  const trimmed = source.trim();
  if (trimmed.length === 0) {
    return `Classified as ${label}.`;
  }

  return trimmed.length > 240 ? `${trimmed.slice(0, 237)}...` : trimmed;
}

export function classifyFailure(input: FailureClassificationInput): FailureClassification | null {
  const combinedText = normalizeText(
    [
      input.failureReason ?? '',
      input.outputText ?? '',
      readErrorText(input.error),
      input.tool ?? '',
      input.modelId ?? '',
      input.modelProvider ?? '',
      input.verdict ?? '',
    ]
      .filter(Boolean)
      .join(' ')
  );

  if (!combinedText) {
    return null;
  }

  const timeoutPatterns = [
    /\btimeout\b/i,
    /\btimed out\b/i,
    /\bdeadline exceeded\b/i,
    /\babort(?:ed|error)\b/i,
  ];
  if (hasAny(combinedText, timeoutPatterns)) {
    return {
      errorType: 'TIMEOUT',
      reason: buildReason(input.failureReason ?? input.outputText ?? readErrorText(input.error), 'TIMEOUT'),
    };
  }

  const toolSignals = [
    /\btool\b/i,
    /\btools\b/i,
    /\bbrowser\b/i,
    /\bmcp\b/i,
    /\bconnector\b/i,
    /\bconnectors\b/i,
    /\bretriev(?:al|e)\b/i,
    /\bweb search\b/i,
  ];
  if ((input.tool && input.tool.trim().length > 0) || hasAny(combinedText, toolSignals)) {
    if (hasAny(combinedText, [/\berror\b/i, /\bfail(?:ed|ure)?\b/i, /\bexception\b/i, /\bunable\b/i, /\bcannot\b/i])) {
      return {
        errorType: 'TOOL_ERROR',
        reason: buildReason(input.failureReason ?? input.outputText ?? readErrorText(input.error), 'TOOL_ERROR'),
      };
    }
  }

  const llmSignals = [
    /\bllm\b/i,
    /\bmodel\b/i,
    /\bprovider\b/i,
    /\bapi key\b/i,
    /\brate limit\b/i,
    /\bquota\b/i,
    /\bopenai\b/i,
    /\banthropic\b/i,
    /\bgemini\b/i,
    /\bclaude\b/i,
    /\bgpt\b/i,
    /\bresponse format\b/i,
  ];
  if (hasAny(combinedText, llmSignals)) {
    if (hasAny(combinedText, [/\berror\b/i, /\bfail(?:ed|ure)?\b/i, /\bexception\b/i, /\binvalid\b/i, /\bnot configured\b/i])) {
      return {
        errorType: 'LLM_ERROR',
        reason: buildReason(input.failureReason ?? input.outputText ?? readErrorText(input.error), 'LLM_ERROR'),
      };
    }
  }

  const outputText = normalizeText(input.outputText ?? '');
  if (!outputText || outputText === 'no final answer was produced.' || outputText === 'no answer was produced.') {
    if (input.verdict !== 'success') {
      return {
        errorType: 'EMPTY_OUTPUT',
        reason: buildReason(input.failureReason ?? input.outputText ?? 'No output was produced.', 'EMPTY_OUTPUT'),
      };
    }
  }

  const badResultSignals = [
    /\bmissing required artifacts\b/i,
    /\bdoes not satisfy\b/i,
    /\bnot grounded\b/i,
    /\bincomplete\b/i,
    /\bdid not pass\b/i,
    /\bcompletion checks\b/i,
    /\bno verified sources\b/i,
    /\bretry\b/i,
    /\bnot enough\b/i,
    /\bunsupported\b/i,
    /\bmismatch\b/i,
  ];
  if (input.verdict === 'failure' || input.verdict === 'retry' || hasAny(combinedText, badResultSignals)) {
    return {
      errorType: 'BAD_RESULT',
      reason: buildReason(input.failureReason ?? input.outputText ?? readErrorText(input.error), 'BAD_RESULT'),
    };
  }

  return null;
}
