import type { RunTraceReport } from './run-trace';

export type RunTraceModelMetrics = {
  modelId: string;
  runCount: number;
  successRate: number;
  retryCount: number;
  avgLatencyMs: number;
  estimatedCostUsd: number;
};

export type RunTraceMetrics = {
  runCount: number;
  successRate: number;
  retryCount: number;
  avgLatencyMs: number;
  estimatedCostUsd: number;
  modelSuccessRateByModel: Record<string, number>;
  modelMetrics: RunTraceModelMetrics[];
};

function round4(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(4)) : 0;
}

export function estimateRunCost(trace: RunTraceReport) {
  return trace.summary.estimatedCostUsd;
}

export function buildRunMetrics(traces: RunTraceReport[]): RunTraceMetrics {
  if (traces.length === 0) {
    return {
      runCount: 0,
      successRate: 0,
      retryCount: 0,
      avgLatencyMs: 0,
      estimatedCostUsd: 0,
      modelSuccessRateByModel: {},
      modelMetrics: [],
    };
  }

  const totals = traces.reduce(
    (accumulator, trace) => {
      const modelId = trace.modelId.trim().length > 0 ? trace.modelId : 'unknown';
      accumulator.runCount += 1;
      accumulator.successCount += trace.summary.success ? 1 : 0;
      accumulator.retryCount += trace.summary.retryCount;
      accumulator.totalLatencyMs += trace.summary.avgLatencyMs;
      accumulator.estimatedCostUsd += estimateRunCost(trace);

      const current = accumulator.models.get(modelId) ?? {
        modelId,
        runCount: 0,
        successCount: 0,
        retryCount: 0,
        totalLatencyMs: 0,
        estimatedCostUsd: 0,
      };

      current.runCount += 1;
      current.successCount += trace.summary.success ? 1 : 0;
      current.retryCount += trace.summary.retryCount;
      current.totalLatencyMs += trace.summary.avgLatencyMs;
      current.estimatedCostUsd += estimateRunCost(trace);
      accumulator.models.set(modelId, current);

      return accumulator;
    },
    {
      runCount: 0,
      successCount: 0,
      retryCount: 0,
      totalLatencyMs: 0,
      estimatedCostUsd: 0,
      models: new Map<
        string,
        {
          modelId: string;
          runCount: number;
          successCount: number;
          retryCount: number;
          totalLatencyMs: number;
          estimatedCostUsd: number;
        }
      >(),
    }
  );

  const modelMetrics: RunTraceModelMetrics[] = [...totals.models.values()]
    .map((item) => ({
      modelId: item.modelId,
      runCount: item.runCount,
      successRate: item.runCount > 0 ? item.successCount / item.runCount : 0,
      retryCount: item.retryCount,
      avgLatencyMs: item.runCount > 0 ? Math.round(item.totalLatencyMs / item.runCount) : 0,
      estimatedCostUsd: round4(item.estimatedCostUsd),
    }))
    .sort((left, right) => right.successRate - left.successRate || right.runCount - left.runCount || left.modelId.localeCompare(right.modelId));

  const modelSuccessRateByModel = Object.fromEntries(
    modelMetrics.map((metric) => [metric.modelId, metric.successRate])
  );

  return {
    runCount: totals.runCount,
    successRate: totals.runCount > 0 ? totals.successCount / totals.runCount : 0,
    retryCount: totals.retryCount,
    avgLatencyMs: Math.round(totals.totalLatencyMs / totals.runCount),
    estimatedCostUsd: round4(totals.estimatedCostUsd),
    modelSuccessRateByModel,
    modelMetrics,
  };
}

