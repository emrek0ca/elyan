import type { ZodTypeAny } from 'zod';
import { CapabilityAuditTrail } from './audit';
import { CapabilityDisabledError, CapabilityNotFoundError, CapabilityTimeoutError } from './errors';
import type {
  CapabilityAuditEntry,
  CapabilityDefinition,
  CapabilityExecutionContext,
  CapabilityRegistration,
} from './types';
import { defaultCapabilityCatalog } from './catalog';
import { classifyFailure } from '@/core/observability/failure-classifier';
import type { RunTraceRecorder } from '@/core/observability/run-trace';

function normalizeDisabledIds(values?: string[]): Set<string> {
  return new Set((values ?? []).map((value) => value.trim()).filter(Boolean));
}

function readDisabledCapabilityIds(): string[] {
  const fromEnv = process.env.ELYAN_DISABLED_CAPABILITIES || '';
  return fromEnv
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
}

function combineSignals(signals: Array<AbortSignal | undefined>): AbortSignal {
  const controller = new AbortController();

  const abort = () => {
    if (!controller.signal.aborted) {
      controller.abort();
    }
  };

  for (const signal of signals) {
    if (!signal) {
      continue;
    }

    if (signal.aborted) {
      abort();
      break;
    }

    signal.addEventListener('abort', abort, { once: true });
  }

  return controller.signal;
}

async function runWithTimeout<T>(
  capabilityId: string,
  timeoutMs: number,
  signal: AbortSignal,
  operation: Promise<T>
): Promise<T> {
  return await new Promise<T>((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new CapabilityTimeoutError(capabilityId, timeoutMs));
    }, timeoutMs);

    const cleanup = () => {
      clearTimeout(timeout);
      signal.removeEventListener('abort', onAbort);
    };

    const onAbort = () => {
      cleanup();
      reject(new CapabilityTimeoutError(capabilityId, timeoutMs));
    };

    if (signal.aborted) {
      cleanup();
      reject(new CapabilityTimeoutError(capabilityId, timeoutMs));
      return;
    }

    signal.addEventListener('abort', onAbort, { once: true });

    operation
      .then((value) => {
        cleanup();
        resolve(value);
      })
      .catch((error) => {
        cleanup();
        reject(error);
      });
  });
}

function extractArtifactRefs(value: unknown): string[] {
  const refs = new Set<string>();

  const add = (candidate: unknown) => {
    if (typeof candidate === 'string' && candidate.trim().length > 0) {
      refs.add(candidate.trim());
    }
  };

  const visit = (candidate: unknown) => {
    if (!candidate) {
      return;
    }

    if (Array.isArray(candidate)) {
      candidate.forEach(visit);
      return;
    }

    if (typeof candidate === 'object') {
      const record = candidate as Record<string, unknown>;
      add(record.id);
      add(record.url);
      add(record.href);
      add(record.uri);
      add(record.filePath);
      add(record.path);
      add(record.sourceUrl);
      add(record.downloadPath);
      add(record.outputPath);
      if (record.artifactRefs) {
        visit(record.artifactRefs);
      }
      if (record.sources) {
        visit(record.sources);
      }
      if (record.pages) {
        visit(record.pages);
      }
    }
  };

  visit(value);
  return [...refs].slice(0, 12);
}

function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return 'unknown error';
}

export class CapabilityRegistry {
  private definitions = new Map<string, CapabilityDefinition<ZodTypeAny, ZodTypeAny>>();

  constructor(private readonly auditTrail = new CapabilityAuditTrail(), registration?: CapabilityRegistration) {
    const disabled = new Set([
      ...readDisabledCapabilityIds(),
      ...normalizeDisabledIds(registration?.disabledCapabilityIds),
    ]);

    for (const capability of defaultCapabilityCatalog) {
      const definition = disabled.has(capability.id)
        ? { ...capability, enabled: false }
        : capability;

      this.register(definition);
    }
  }

  register(definition: CapabilityDefinition<ZodTypeAny, ZodTypeAny>) {
    if (this.definitions.has(definition.id)) {
      throw new Error(`Capability already registered: ${definition.id}`);
    }

    this.definitions.set(definition.id, definition);
  }

  get(capabilityId: string) {
    const definition = this.definitions.get(capabilityId);
    if (!definition) {
      throw new CapabilityNotFoundError(capabilityId);
    }

    return definition;
  }

  list(options?: { includeDisabled?: boolean }) {
    const capabilities = [...this.definitions.values()]
      .map((capability) => ({
        id: capability.id,
        title: capability.title,
        description: capability.description,
        library: capability.library,
        timeoutMs: capability.timeoutMs,
        enabled: capability.enabled,
      }))
      .sort((left, right) => left.id.localeCompare(right.id) || left.title.localeCompare(right.title));

    if (options?.includeDisabled) {
      return capabilities;
    }

    return capabilities.filter((capability) => capability.enabled);
  }

  getAuditTrail(): CapabilityAuditEntry[] {
    return this.auditTrail.list();
  }

  async execute(
    capabilityId: string,
    rawInput: unknown,
    options?: {
      signal?: AbortSignal;
      runtime?: CapabilityExecutionContext['runtime'];
      trace?: RunTraceRecorder;
      artifactRefs?: string[];
    }
  ) {
    const definition = this.get(capabilityId);
    const traceContext = options?.trace;
    const traceDetails = {
      capabilityId: definition.id,
      capabilityTitle: definition.title,
      recoveryState: options?.runtime?.recoveryState,
      taskId: options?.runtime?.taskId,
    };

    traceContext?.recordCapabilityStarted({
      step: 0,
      capabilityId: definition.id,
      modelId: definition.id,
      tool: definition.id,
      retryCount: 0,
      recoveryState: options?.runtime?.recoveryState,
      details: traceDetails,
    });

    if (!definition.enabled) {
      const startedAt = new Date();
      const finishedAt = new Date();

      this.auditTrail.record({
        capabilityId: definition.id,
        title: definition.title,
        status: 'disabled',
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: 0,
        errorMessage: 'disabled by registry configuration',
      });

      traceContext?.recordCapabilityCompleted({
        step: 0,
        capabilityId: definition.id,
        modelId: definition.id,
        tool: definition.id,
        latencyMs: 0,
        success: false,
        status: 'blocked',
        retryCount: 0,
        artifactRefs: [],
        recoveryState: options?.runtime?.recoveryState,
        details: {
          ...traceDetails,
          status: 'disabled',
        },
      });

      throw new CapabilityDisabledError(definition.id, 'disabled by registry configuration');
    }

    const startedAt = new Date();

    try {
      const parsedInput = definition.inputSchema.parse(rawInput);
      const signal = combineSignals([options?.signal]);
      const result = await runWithTimeout(
        definition.id,
        definition.timeoutMs,
        signal,
        Promise.resolve(
          definition.run(parsedInput, {
            signal,
            runtime: options?.runtime,
          } as CapabilityExecutionContext)
        )
      );

      const parsedOutput = definition.outputSchema.parse(result);
      const finishedAt = new Date();
      const artifactRefs = options?.artifactRefs ?? extractArtifactRefs(parsedOutput);

      this.auditTrail.record({
        capabilityId: definition.id,
        title: definition.title,
        status: 'success',
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: finishedAt.getTime() - startedAt.getTime(),
      });

      traceContext?.recordCapabilityCompleted({
        step: 0,
        capabilityId: definition.id,
        modelId: definition.id,
        tool: definition.id,
        latencyMs: finishedAt.getTime() - startedAt.getTime(),
        success: true,
        status: 'success',
        retryCount: 0,
        artifactRefs,
        recoveryState: options?.runtime?.recoveryState,
        details: {
          ...traceDetails,
          artifactCount: artifactRefs.length,
          status: 'success',
        },
      });

      return parsedOutput;
    } catch (error) {
      const finishedAt = new Date();
      const status = error instanceof CapabilityTimeoutError ? 'timeout' : 'error';
      const errorType = classifyFailure({
        error,
        failureReason: describeError(error),
        verdict: 'failure',
        tool: definition.id,
      })?.errorType;

      this.auditTrail.record({
        capabilityId: definition.id,
        title: definition.title,
        status,
        startedAt: startedAt.toISOString(),
        finishedAt: finishedAt.toISOString(),
        durationMs: finishedAt.getTime() - startedAt.getTime(),
        errorMessage: describeError(error),
      });

      traceContext?.recordCapabilityCompleted({
        step: 0,
        capabilityId: definition.id,
        modelId: definition.id,
        tool: definition.id,
        latencyMs: finishedAt.getTime() - startedAt.getTime(),
        success: false,
        status: options?.signal?.aborted ? 'cancelled' : status === 'timeout' ? 'failure' : 'failure',
        retryCount: 0,
        errorType,
        artifactRefs: [],
        recoveryState: options?.runtime?.recoveryState,
        details: {
          ...traceDetails,
          status,
          error: describeError(error),
        },
      });

      throw error;
    }
  }
}

export const capabilityRegistry = new CapabilityRegistry();
