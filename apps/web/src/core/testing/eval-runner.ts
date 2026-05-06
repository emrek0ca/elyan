import { buildRunMetrics, type RunTraceMetrics } from '@/core/observability/metrics';
import { defaultSimulationScenarios, replayRun, simulateScenario, type ScenarioReplayComparison, type ScenarioSimulationResult, type ScenarioSimulationTrace, type SimulationOptions, type SimulationScenario } from './simulator';

export type ScenarioSuiteEntry = {
  scenario: SimulationScenario;
  result: ScenarioSimulationResult;
};

export type ScenarioSuiteSummary = {
  runCount: number;
  passCount: number;
  failureCount: number;
  averageScores: {
    decisionQuality: number;
    executionEfficiency: number;
    retryEffectiveness: number;
    toolUsageCorrectness: number;
    overall: number;
  };
  traceMetrics: RunTraceMetrics;
  failureSummary: Array<{
    scenarioId: string;
    kind: SimulationScenario['kind'];
    failureType: string;
    reason: string;
  }>;
};

export type ScenarioSuiteReport = {
  runAt: string;
  scenarios: SimulationScenario[];
  entries: ScenarioSuiteEntry[];
  summary: ScenarioSuiteSummary;
};

export type BaselineScenarioDiff = {
  scenarioId: string;
  kind: SimulationScenario['kind'];
  scoreDiff: {
    decisionQuality: number;
    executionEfficiency: number;
    retryEffectiveness: number;
    toolUsageCorrectness: number;
    overall: number;
  };
  passChanged: boolean;
  regression: boolean;
  failureSummary: string[];
};

export type BaselineComparisonReport = {
  regression: boolean;
  runAt: string;
  baselineRunAt: string;
  scoreDiff: {
    decisionQuality: number;
    executionEfficiency: number;
    retryEffectiveness: number;
    toolUsageCorrectness: number;
    overall: number;
    passRate: number;
  };
  failureSummary: string[];
  regressions: BaselineScenarioDiff[];
  improvements: BaselineScenarioDiff[];
  unchanged: BaselineScenarioDiff[];
};

export type ReplayRealRunsEntry = {
  original: ScenarioSimulationTrace;
  replay: ScenarioSimulationResult;
  comparison: ScenarioReplayComparison;
};

export type ReplayRealRunsReport = {
  runAt: string;
  traces: ScenarioSimulationTrace[];
  entries: ReplayRealRunsEntry[];
  summary: ScenarioSuiteSummary;
};

export type EvalRunnerOptions = SimulationOptions & {
  scenarios?: SimulationScenario[];
};

function round4(value: number) {
  return Number.isFinite(value) ? Number(value.toFixed(4)) : 0;
}

function average(values: number[]) {
  if (values.length === 0) {
    return 0;
  }

  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function buildSuiteSummary(entries: ScenarioSuiteEntry[]): ScenarioSuiteSummary {
  const runCount = entries.length;
  const passCount = entries.filter((entry) => entry.result.evaluation.pass).length;
  const failureCount = runCount - passCount;
  const failureSummary = entries
    .filter((entry) => !entry.result.evaluation.pass)
    .map((entry) => ({
      scenarioId: entry.scenario.id,
      kind: entry.scenario.kind,
      failureType: entry.result.trace.summary.failureType ?? 'BAD_RESULT',
      reason: entry.result.trace.summary.failureType ?? 'Scenario evaluation failed.',
    }));

  const traceMetrics = buildRunMetrics(entries.map((entry) => entry.result.trace));

  return {
    runCount,
    passCount,
    failureCount,
    averageScores: {
      decisionQuality: round4(average(entries.map((entry) => entry.result.evaluation.scores.decisionQuality))),
      executionEfficiency: round4(average(entries.map((entry) => entry.result.evaluation.scores.executionEfficiency))),
      retryEffectiveness: round4(average(entries.map((entry) => entry.result.evaluation.scores.retryEffectiveness))),
      toolUsageCorrectness: round4(average(entries.map((entry) => entry.result.evaluation.scores.toolUsageCorrectness))),
      overall: round4(average(entries.map((entry) => entry.result.evaluation.scores.overall))),
    },
    traceMetrics,
    failureSummary,
  };
}

export async function runScenarioSuite(options: EvalRunnerOptions = {}): Promise<ScenarioSuiteReport> {
  const scenarios = options.scenarios ?? defaultSimulationScenarios;
  const entries: ScenarioSuiteEntry[] = [];
  const scenarioOptions: SimulationOptions = {
    ...options,
    recordFailureLearning: false,
    allowFailureLearningRerun: false,
  };

  for (const scenario of scenarios) {
    const result = await simulateScenario(scenario, scenarioOptions);
    entries.push({ scenario, result });
  }

  return {
    runAt: new Date().toISOString(),
    scenarios,
    entries,
    summary: buildSuiteSummary(entries),
  };
}

function buildScenarioIndex(report: ScenarioSuiteReport) {
  return new Map(report.entries.map((entry) => [entry.scenario.id, entry]));
}

function diffScore(current: number, baseline: number) {
  return round4(current - baseline);
}

export function compareBaseline(current: ScenarioSuiteReport, baseline: ScenarioSuiteReport, regressionThreshold = 0.05): BaselineComparisonReport {
  const currentIndex = buildScenarioIndex(current);
  const baselineIndex = buildScenarioIndex(baseline);
  const scenarioIds = new Set([...currentIndex.keys(), ...baselineIndex.keys()]);
  const regressions: BaselineScenarioDiff[] = [];
  const improvements: BaselineScenarioDiff[] = [];
  const unchanged: BaselineScenarioDiff[] = [];

  for (const scenarioId of scenarioIds) {
    const currentEntry = currentIndex.get(scenarioId);
    const baselineEntry = baselineIndex.get(scenarioId);

    if (!currentEntry || !baselineEntry) {
      continue;
    }

    const scoreDiff = {
      decisionQuality: diffScore(currentEntry.result.evaluation.scores.decisionQuality, baselineEntry.result.evaluation.scores.decisionQuality),
      executionEfficiency: diffScore(currentEntry.result.evaluation.scores.executionEfficiency, baselineEntry.result.evaluation.scores.executionEfficiency),
      retryEffectiveness: diffScore(currentEntry.result.evaluation.scores.retryEffectiveness, baselineEntry.result.evaluation.scores.retryEffectiveness),
      toolUsageCorrectness: diffScore(currentEntry.result.evaluation.scores.toolUsageCorrectness, baselineEntry.result.evaluation.scores.toolUsageCorrectness),
      overall: diffScore(currentEntry.result.evaluation.scores.overall, baselineEntry.result.evaluation.scores.overall),
    };

    const passChanged = currentEntry.result.evaluation.pass !== baselineEntry.result.evaluation.pass;
    const regression =
      (!currentEntry.result.evaluation.pass && baselineEntry.result.evaluation.pass) ||
      scoreDiff.overall <= -regressionThreshold ||
      scoreDiff.decisionQuality <= -regressionThreshold ||
      scoreDiff.executionEfficiency <= -regressionThreshold ||
      scoreDiff.retryEffectiveness <= -regressionThreshold ||
      scoreDiff.toolUsageCorrectness <= -regressionThreshold;

    const entry: BaselineScenarioDiff = {
      scenarioId,
      kind: currentEntry.scenario.kind,
      scoreDiff,
      passChanged,
      regression,
      failureSummary: currentEntry.result.evaluation.diffs.map((diff) => `${diff.field}: ${diff.reason}`),
    };

    if (regression) {
      regressions.push(entry);
    } else if (
      currentEntry.result.evaluation.pass &&
      !baselineEntry.result.evaluation.pass
    ) {
      improvements.push(entry);
    } else {
      unchanged.push(entry);
    }
  }

  const scoreDiff = {
    decisionQuality: diffScore(current.summary.averageScores.decisionQuality, baseline.summary.averageScores.decisionQuality),
    executionEfficiency: diffScore(current.summary.averageScores.executionEfficiency, baseline.summary.averageScores.executionEfficiency),
    retryEffectiveness: diffScore(current.summary.averageScores.retryEffectiveness, baseline.summary.averageScores.retryEffectiveness),
    toolUsageCorrectness: diffScore(current.summary.averageScores.toolUsageCorrectness, baseline.summary.averageScores.toolUsageCorrectness),
    overall: diffScore(current.summary.averageScores.overall, baseline.summary.averageScores.overall),
    passRate: round4((current.summary.passCount / Math.max(1, current.summary.runCount)) - (baseline.summary.passCount / Math.max(1, baseline.summary.runCount))),
  };

  return {
    regression: regressions.length > 0 || scoreDiff.overall < 0,
    runAt: current.runAt,
    baselineRunAt: baseline.runAt,
    scoreDiff,
    failureSummary: current.summary.failureSummary.map((item) => `${item.scenarioId}: ${item.failureType}`),
    regressions,
    improvements,
    unchanged,
  };
}

function buildReplaySummary(entries: ReplayRealRunsEntry[]): ScenarioSuiteSummary {
  return buildSuiteSummary(
    entries.map((entry) => ({
      scenario: entry.original.scenario,
      result: entry.replay,
    }))
  );
}

export async function replayRealRuns(traces: ScenarioSimulationTrace[], options: SimulationOptions = {}): Promise<ReplayRealRunsReport> {
  const entries: ReplayRealRunsEntry[] = [];
  const replayOptions: SimulationOptions = {
    ...options,
    recordFailureLearning: false,
    allowFailureLearningRerun: false,
  };

  for (const trace of traces) {
    const replay = await replayRun(trace, replayOptions);
    entries.push({
      original: trace,
      replay: replay.rerun,
      comparison: replay.comparison,
    });
  }

  return {
    runAt: new Date().toISOString(),
    traces,
    entries,
    summary: buildReplaySummary(entries),
  };
}
