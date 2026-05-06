import { searchRetrievalDocumentsHybrid, type RetrievalDocumentRecord } from '@/core/retrieval';
import { runSelectiveWebRetrieval, type SelectiveWebRetrievalResult } from '@/core/retrieval/web';
import { loadLearningPromptHints, loadLearningRoutingHints } from '@/core/control-plane/learning/signal-extractor';
import { classifyFailure } from '@/core/observability/failure-classifier';
import type { RunTraceRecorder, RunTraceRecoveryState } from '@/core/observability/run-trace';
import type { OrchestrationPlan } from '@/core/orchestration';
import type { ScrapedContent } from '@/types/search';

export type ConnectorFetchInput = {
  query: string;
  accountId?: string | null;
  spaceId?: string | null;
  signal?: AbortSignal;
  plan?: OrchestrationPlan;
  searchEnabled?: boolean;
  limit?: number;
  modelId?: string;
  trace?: RunTraceRecorder;
  recoveryState?: RunTraceRecoveryState;
};

export type ConnectorFetchResult = {
  connectorId: string;
  health?: ConnectorHealthSnapshot;
  contextBlocks: string[];
  sources: ScrapedContent[];
  storedContexts: RetrievalDocumentRecord[];
  searchAvailable?: boolean;
  liveSearchUsed?: boolean;
  error?: string;
};

type ConnectorDefinition = {
  id: 'stored_contexts' | 'learning_hints' | 'web_evidence';
  title: string;
  layer: 'retrieval' | 'learning' | 'web';
  fetch(input: ConnectorFetchInput): Promise<ConnectorFetchResult>;
};

export type ConnectorHealthStatus = 'healthy' | 'degraded' | 'blocked' | 'unavailable';

export type ConnectorHealthSnapshot = {
  connectorId: ConnectorDefinition['id'];
  status: ConnectorHealthStatus;
  failureCount: number;
  consecutiveFailures: number;
  lastSuccessAt?: string;
  lastFailureAt?: string;
  failureType?: string;
  lastError?: string;
  retryAfterMs?: number;
  updatedAt: string;
};

const connectorHealth = new Map<ConnectorDefinition['id'], ConnectorHealthSnapshot>();
const connectorRetryBackoffMs = [120, 240];

function formatStoredContext(entry: RetrievalDocumentRecord) {
  const title = entry.title?.trim() || entry.sourceName;
  const url = entry.sourceUrl?.trim();
  const prefix = `${entry.sourceKind.toUpperCase()} ${title}`;

  return [
    prefix,
    url ? `URL: ${url}` : '',
    entry.content,
  ]
    .filter(Boolean)
    .join('\n');
}

function uniqueSources(sources: ScrapedContent[]) {
  const seen = new Set<string>();
  return sources.filter((source) => {
    if (seen.has(source.url)) {
      return false;
    }

    seen.add(source.url);
    return true;
  });
}

function nowIso() {
  return new Date().toISOString();
}

function defaultConnectorHealth(connectorId: ConnectorDefinition['id']): ConnectorHealthSnapshot {
  return connectorHealth.get(connectorId) ?? {
    connectorId,
    status: 'healthy',
    failureCount: 0,
    consecutiveFailures: 0,
    updatedAt: nowIso(),
  };
}

function updateConnectorHealth(
  connectorId: ConnectorDefinition['id'],
  patch: Partial<ConnectorHealthSnapshot>
) {
  const next: ConnectorHealthSnapshot = {
    ...defaultConnectorHealth(connectorId),
    ...patch,
    connectorId,
    updatedAt: nowIso(),
  };
  connectorHealth.set(connectorId, next);
  return next;
}

function validateConnectorScope(input: ConnectorFetchInput, connector: ConnectorDefinition) {
  const query = input.query.trim();
  if (!query) {
    return {
      allowed: false,
      reason: `Connector ${connector.id} requires a non-empty query.`,
      status: 'blocked' as const,
    };
  }

  if ((input.accountId != null && input.accountId.trim().length === 0) || (input.spaceId != null && input.spaceId.trim().length === 0)) {
    return {
      allowed: false,
      reason: `Connector ${connector.id} received an invalid scope identifier.`,
      status: 'blocked' as const,
    };
  }

  return { allowed: true as const };
}

function readArtifactRefs(result: ConnectorFetchResult) {
  const refs = new Set<string>();
  result.storedContexts.forEach((context) => {
    refs.add(context.documentId);
    if (context.sourceUrl) {
      refs.add(context.sourceUrl);
    }
  });
  result.sources.forEach((source) => {
    refs.add(source.url);
  });
  return [...refs].slice(0, 12);
}

async function delay(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

function buildFailedConnectorResult(connectorId: ConnectorDefinition['id'], health: ConnectorHealthSnapshot, error: string): ConnectorFetchResult {
  return {
    connectorId,
    health,
    contextBlocks: [],
    sources: [],
    storedContexts: [],
    error,
    searchAvailable: false,
    liveSearchUsed: false,
  };
}

async function executeConnectorWithHardening(
  connector: ConnectorDefinition,
  input: ConnectorFetchInput
): Promise<ConnectorFetchResult> {
  const scope = validateConnectorScope(input, connector);
  const traceId = input.trace?.getTraceId() ?? 'unknown';

  if (!scope.allowed) {
    const currentHealth = defaultConnectorHealth(connector.id);
    const health = updateConnectorHealth(connector.id, {
      status: scope.status,
      lastFailureAt: nowIso(),
      failureCount: currentHealth.failureCount + 1,
      consecutiveFailures: currentHealth.consecutiveFailures + 1,
      lastError: scope.reason,
      failureType: 'BAD_RESULT',
      retryAfterMs: connectorRetryBackoffMs[0],
    });

    input.trace?.recordCapabilityStarted({
      step: 0,
      capabilityId: `connector:${connector.id}`,
      modelId: input.modelId ?? connector.id,
      tool: connector.id,
      retryCount: 0,
      recoveryState: input.recoveryState,
      details: {
        connectorLayer: connector.layer,
        scopeReason: scope.reason,
        traceId,
      },
    });
    input.trace?.recordCapabilityCompleted({
      step: 0,
      capabilityId: `connector:${connector.id}`,
      modelId: input.modelId ?? connector.id,
      tool: connector.id,
      latencyMs: 0,
      success: false,
      status: 'blocked',
      retryCount: 0,
      errorType: 'BAD_RESULT',
      artifactRefs: [],
      recoveryState: input.recoveryState,
      details: {
        connectorLayer: connector.layer,
        scopeReason: scope.reason,
        traceId,
      },
    });

    return buildFailedConnectorResult(connector.id, health, scope.reason);
  }

  let lastError: string | undefined;
  let lastFailureType: string | undefined;
  let previousHealth = defaultConnectorHealth(connector.id);

  for (let attempt = 0; attempt < connectorRetryBackoffMs.length + 1; attempt += 1) {
    if (input.signal?.aborted) {
      const health = updateConnectorHealth(connector.id, {
        status: 'blocked',
        lastFailureAt: nowIso(),
        failureCount: previousHealth.failureCount + 1,
        consecutiveFailures: previousHealth.consecutiveFailures + 1,
        lastError: 'Operation aborted.',
        failureType: 'TIMEOUT',
        retryAfterMs: connectorRetryBackoffMs[attempt - 1] ?? connectorRetryBackoffMs.at(-1),
      });

      return buildFailedConnectorResult(connector.id, health, 'Operation aborted.');
    }

    const startedAt = Date.now();
    input.trace?.recordCapabilityStarted({
      step: attempt + 1,
      capabilityId: `connector:${connector.id}`,
      modelId: input.modelId ?? connector.id,
      tool: connector.id,
      retryCount: attempt,
      recoveryState: input.recoveryState,
      details: {
        connectorLayer: connector.layer,
        traceId,
        attempt,
      },
    });

    try {
      const result = await connector.fetch(input);
      const health = updateConnectorHealth(connector.id, {
        status: 'healthy',
        lastSuccessAt: nowIso(),
        failureCount: previousHealth.failureCount,
        consecutiveFailures: 0,
        lastError: undefined,
        failureType: undefined,
        retryAfterMs: undefined,
      });

      const artifactRefs = readArtifactRefs(result);
      input.trace?.recordCapabilityCompleted({
        step: attempt + 1,
        capabilityId: `connector:${connector.id}`,
        modelId: input.modelId ?? connector.id,
        tool: connector.id,
        latencyMs: Date.now() - startedAt,
        success: true,
        status: 'success',
        retryCount: attempt,
        artifactRefs,
        recoveryState: input.recoveryState,
        details: {
          connectorLayer: connector.layer,
          traceId,
          artifactCount: artifactRefs.length,
          liveSearchUsed: result.liveSearchUsed,
          searchAvailable: result.searchAvailable,
        },
      });

      return {
        ...result,
        health,
      };
    } catch (error) {
      const failure = classifyFailure({
        error,
        failureReason: error instanceof Error ? error.message : 'Connector fetch failed.',
        verdict: 'failure',
        tool: connector.id,
        modelId: input.modelId,
      });
      const failureMessage = error instanceof Error ? error.message : String(error);
      lastError = failureMessage;
      lastFailureType = failure?.errorType ?? 'BAD_RESULT';
      const nextHealth = updateConnectorHealth(connector.id, {
        status: 'degraded',
        lastFailureAt: nowIso(),
        failureCount: previousHealth.failureCount + 1,
        consecutiveFailures: previousHealth.consecutiveFailures + 1,
        lastError: failureMessage,
        failureType: lastFailureType,
        retryAfterMs: connectorRetryBackoffMs[attempt] ?? connectorRetryBackoffMs.at(-1),
      });

      input.trace?.recordCapabilityCompleted({
        step: attempt + 1,
        capabilityId: `connector:${connector.id}`,
        modelId: input.modelId ?? connector.id,
        tool: connector.id,
        latencyMs: Date.now() - startedAt,
        success: false,
        status: 'failure',
        retryCount: attempt,
        errorType: failure?.errorType,
        artifactRefs: [],
        recoveryState: input.recoveryState,
        details: {
          connectorLayer: connector.layer,
          traceId,
          attempt,
          error: failureMessage,
          failureType: failure?.errorType,
        },
      });

      previousHealth = nextHealth;

      if (input.signal?.aborted || attempt >= connectorRetryBackoffMs.length) {
        return buildFailedConnectorResult(connector.id, nextHealth, failureMessage);
      }

      await delay(connectorRetryBackoffMs[attempt]);
    }
  }

  const health = updateConnectorHealth(connector.id, {
    status: 'degraded',
    lastFailureAt: nowIso(),
    failureCount: previousHealth.failureCount + 1,
    consecutiveFailures: previousHealth.consecutiveFailures + 1,
    lastError: lastError ?? 'Connector failed.',
    failureType: lastFailureType ?? 'BAD_RESULT',
    retryAfterMs: connectorRetryBackoffMs.at(-1),
  });

  return buildFailedConnectorResult(connector.id, health, lastError ?? 'Connector failed.');
}

const connectorRegistry: ConnectorDefinition[] = [
  {
    id: 'stored_contexts',
    title: 'Stored retrieval context',
    layer: 'retrieval',
    async fetch(input) {
      const storedContexts = await searchRetrievalDocumentsHybrid(input.query, {
        accountId: input.accountId,
        spaceId: input.spaceId,
        sourceKinds: ['bootstrap', 'learning', 'web'],
        limit: input.limit ?? 6,
      });

      return {
        connectorId: 'stored_contexts',
        contextBlocks: storedContexts.map(formatStoredContext),
        sources: [],
        storedContexts,
      };
    },
  },
  {
    id: 'learning_hints',
    title: 'Learning hints',
    layer: 'learning',
    async fetch(input) {
      const hints = await loadLearningPromptHints({
        taskType: input.plan?.taskIntent ?? 'direct_answer',
        modelId: input.modelId,
        spaceId: input.spaceId ?? undefined,
        limit: input.limit ?? 6,
      });
      const routingHint = await loadLearningRoutingHints({
        taskType: input.plan?.taskIntent ?? 'direct_answer',
        modelId: input.modelId,
        spaceId: input.spaceId ?? undefined,
        limit: 6,
      });

      return {
        connectorId: 'learning_hints',
        contextBlocks: [
          ...hints,
          routingHint.reason ? `[learning:routing] ${routingHint.reason}` : '',
        ].filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0),
        sources: [],
        storedContexts: [],
      };
    },
  },
  {
    id: 'web_evidence',
    title: 'Live web evidence',
    layer: 'web',
    async fetch(input) {
      const result: SelectiveWebRetrievalResult = await runSelectiveWebRetrieval({
        query: input.query,
        accountId: input.accountId,
        spaceId: input.spaceId,
        plan: input.plan,
        searchEnabled: input.searchEnabled,
        signal: input.signal,
      });

      return {
        connectorId: 'web_evidence',
        contextBlocks: result.contextBlocks,
        sources: uniqueSources(result.sources),
        storedContexts: result.storedContexts,
        searchAvailable: result.searchAvailable,
        liveSearchUsed: result.liveSearchUsed,
      };
    },
  },
];

export function listConnectorRegistry() {
  return connectorRegistry.map(({ id, title, layer }) => ({ id, title, layer }));
}

export async function fetchConnectorBundle(input: ConnectorFetchInput) {
  const results: ConnectorFetchResult[] = [];
  for (const connector of connectorRegistry) {
    if (input.signal?.aborted) {
      throw new Error('Operation aborted.');
    }

    results.push(await executeConnectorWithHardening(connector, input));
  }
  return results;
}

export function getConnectorHealthSnapshot() {
  return connectorRegistry.map((connector) => defaultConnectorHealth(connector.id));
}
