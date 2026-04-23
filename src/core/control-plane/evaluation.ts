import type {
  ControlPlaneEvaluationQuality,
  ControlPlaneEvaluationSignal,
} from './types';

export type ControlPlaneEvaluationSummary = {
  windowCount: number;
  latestSignal?: {
    signalId: string;
    createdAt: string;
    mode: ControlPlaneEvaluationSignal['mode'];
    taskIntent: ControlPlaneEvaluationSignal['taskIntent'];
    routingMode: ControlPlaneEvaluationSignal['routingMode'];
    quality: ControlPlaneEvaluationQuality;
    modelId: string;
    modelProvider: string;
    sourceCount: number;
    citationCount: number;
    toolCallCount: number;
    latencyMs: number;
  };
  qualityCounts: Record<ControlPlaneEvaluationQuality, number>;
  promotionCandidates: number;
};

export function buildControlPlaneEvaluationSummary(
  signals: ControlPlaneEvaluationSignal[]
): ControlPlaneEvaluationSummary {
  const qualityCounts: Record<ControlPlaneEvaluationQuality, number> = {
    good: 0,
    mixed: 0,
    poor: 0,
    skipped: 0,
  };

  let promotionCandidates = 0;

  for (const signal of signals) {
    qualityCounts[signal.quality] += 1;
    if (signal.promotionCandidate) {
      promotionCandidates += 1;
    }
  }

  const latestSignal = signals.reduce<ControlPlaneEvaluationSignal | undefined>((latest, signal) => {
    if (!latest) {
      return signal;
    }

    return Date.parse(signal.createdAt) >= Date.parse(latest.createdAt) ? signal : latest;
  }, undefined);

  return {
    windowCount: signals.length,
    latestSignal: latestSignal
      ? {
          signalId: latestSignal.signalId,
          createdAt: latestSignal.createdAt,
          mode: latestSignal.mode,
          taskIntent: latestSignal.taskIntent,
          routingMode: latestSignal.routingMode,
          quality: latestSignal.quality,
          modelId: latestSignal.model.modelId,
          modelProvider: latestSignal.model.provider,
          sourceCount: latestSignal.retrieval.sourceCount,
          citationCount: latestSignal.retrieval.citationCount,
          toolCallCount: latestSignal.tooling.toolCallCount,
          latencyMs: latestSignal.latencyMs,
        }
      : undefined,
    qualityCounts,
    promotionCandidates,
  };
}
