import postgres from "postgres";
import { loadEnv } from "../config/env.js";

type NumericLike = number | string | bigint | null | undefined;

export type ProviderInvocationAggregateRow = {
  provider: string;
  model: string;
  workload: string;
  route: string;
  status: string;
  call_count: NumericLike;
  prompt_tokens: NumericLike;
  completion_tokens: NumericLike;
  total_tokens: NumericLike;
  avg_latency_ms: NumericLike;
  p95_latency_ms: NumericLike;
};

export type TurnMetricAggregateRow = {
  workload: string;
  turn_count: NumericLike;
  avg_total_ms: NumericLike;
  avg_first_delta_ms: NumericLike;
  p95_total_ms: NumericLike;
  model_call_count: NumericLike;
  reasoning_passes: NumericLike;
  refinement_applied_count: NumericLike;
  rate_limited_count: NumericLike;
  deduped_inflight_count: NumericLike;
  cheap_social_turn_count: NumericLike;
  zero_model_call_count: NumericLike;
  single_model_call_count: NumericLike;
  multi_model_pass_count: NumericLike;
  deduped_cost_bucket_count: NumericLike;
};

export type ElyanModelReadinessRow = {
  ready_model_count: NumericLike;
  latest_model_id: string | null;
  latest_model_scope: string | null;
  latest_model_provider: string | null;
  latest_base_model: string | null;
  latest_adapter_kind: string | null;
  latest_evaluation_score: NumericLike;
  latest_quality_composite_score: NumericLike;
  latest_promotion_gate: string | null;
  latest_updated_at: string | Date | null;
};

export type ElyanTrainingReadinessRow = {
  queued_jobs: NumericLike;
  running_jobs: NumericLike;
  latest_job_id: string | null;
  latest_job_status: string | null;
  latest_job_kind: string | null;
  latest_job_base_model: string | null;
  latest_job_updated_at: string | Date | null;
};

export type ElyanDatasetReadinessRow = {
  sft_ready_dataset_count: NumericLike;
  compact_eligible_dataset_count: NumericLike;
  latest_dataset_id: string | null;
  latest_dataset_version: string | null;
  latest_compaction_quality_score: NumericLike;
  latest_dataset_updated_at: string | Date | null;
};

export type AiCostReport = {
  generatedAt: string;
  windowHours: number;
  since: string;
  providerInvocations: {
    totalCalls: number;
    totalTokens: number;
    promptTokens: number;
    completionTokens: number;
    errorCalls: number;
    fallbackCalls: number;
    byWorkload: Record<
      string,
      {
        calls: number;
        totalTokens: number;
        errorCalls: number;
        fallbackCalls: number;
      }
    >;
    byModel: Array<{
      provider: string;
      model: string;
      workload: string;
      route: string;
      status: string;
      calls: number;
      promptTokens: number;
      completionTokens: number;
      totalTokens: number;
      avgLatencyMs: number | null;
      p95LatencyMs: number | null;
    }>;
  };
  turnMetrics: {
    totalTurns: number;
    modelCallCount: number;
    reasoningPasses: number;
    refinementAppliedCount: number;
    rateLimitedCount: number;
    dedupedInflightCount: number;
    cheapSocialTurnCount: number;
    zeroModelCallCount: number;
    singleModelCallCount: number;
    multiModelPassCount: number;
    dedupedCostBucketCount: number;
    byWorkload: Array<{
      workload: string;
      turns: number;
      avgTotalMs: number | null;
      avgFirstDeltaMs: number | null;
      p95TotalMs: number | null;
      modelCallCount: number;
      reasoningPasses: number;
      refinementAppliedCount: number;
      rateLimitedCount: number;
      dedupedInflightCount: number;
      cheapSocialTurnCount: number;
      zeroModelCallCount: number;
      singleModelCallCount: number;
      multiModelPassCount: number;
      dedupedCostBucketCount: number;
    }>;
  };
  elyanModel: {
    readyModelCount: number;
    activeTrainingJobs: number;
    queuedTrainingJobs: number;
    readySftDatasets: number;
    compactEligibleDatasets: number;
    latestModel: {
      id: string | null;
      scope: string | null;
      provider: string | null;
      baseModel: string | null;
      adapterKind: string | null;
      evaluationScore: number | null;
      qualityCompositeScore: number | null;
      promotionGate: string | null;
      updatedAt: string | null;
    };
    latestTrainingJob: {
      id: string | null;
      status: string | null;
      kind: string | null;
      baseModel: string | null;
      updatedAt: string | null;
    };
    latestSftDataset: {
      id: string | null;
      version: string | null;
      compactionQualityScore: number | null;
      updatedAt: string | null;
    };
    nextAction:
      | "wait_for_active_training_job"
      | "export_sft_ready_corrections_dataset"
      | "queue_elyan_model_refresh"
      | "run_shadow_evaluation"
      | "enable_canary_after_operator_review"
      | "promote_elyan_primary_after_operator_review"
      | "groq_retirement_candidate";
    promotionFlags: {
      canaryEnabled: boolean;
      primaryEnabled: boolean;
    };
    liveRoutingCandidate: boolean;
    recommendedCommand: string;
    blockers: string[];
  };
};

function toNumber(value: NumericLike): number {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === "bigint") {
    return Number(value);
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function nullableNumber(value: NumericLike, options: { round?: boolean } = {}): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  const parsed = toNumber(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return options.round === false ? parsed : Math.round(parsed);
}

function nullableIso(value: string | Date | null | undefined): string | null {
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString();
  }
  return null;
}

function firstRow<T>(rows: T[] | undefined): T | null {
  return Array.isArray(rows) && rows.length > 0 ? (rows[0] ?? null) : null;
}

function buildElyanModelReadiness(input: {
  modelRows?: ElyanModelReadinessRow[];
  trainingRows?: ElyanTrainingReadinessRow[];
  datasetRows?: ElyanDatasetReadinessRow[];
  canaryEnabled?: boolean;
  primaryEnabled?: boolean;
}): AiCostReport["elyanModel"] {
  const model = firstRow(input.modelRows);
  const training = firstRow(input.trainingRows);
  const dataset = firstRow(input.datasetRows);
  const readyModelCount = toNumber(model?.ready_model_count);
  const runningJobs = toNumber(training?.running_jobs);
  const queuedJobs = toNumber(training?.queued_jobs);
  const activeTrainingJobs = runningJobs + queuedJobs;
  const readySftDatasets = toNumber(dataset?.sft_ready_dataset_count);
  const compactEligibleDatasets = toNumber(dataset?.compact_eligible_dataset_count);
  const evaluationScore = nullableNumber(model?.latest_evaluation_score, { round: false });
  const qualityCompositeScore = nullableNumber(model?.latest_quality_composite_score, { round: false });
  const blockers: string[] = [];
  const canaryEnabled = input.canaryEnabled === true;
  const primaryEnabled = input.primaryEnabled === true;

  if (activeTrainingJobs > 0) {
    blockers.push("active_training_job_in_progress");
  }
  if (readySftDatasets <= 0) {
    blockers.push("sft_ready_dataset_missing");
  }
  if (readySftDatasets > 0 && compactEligibleDatasets <= 0) {
    blockers.push("compact_eligible_dataset_missing");
  }
  if (readyModelCount <= 0) {
    blockers.push("ready_elyan_model_missing");
  }
  if (readyModelCount > 0 && (evaluationScore ?? 0) < 0.72) {
    blockers.push("evaluation_score_below_canary_gate");
  }
  if (readyModelCount > 0 && (evaluationScore ?? 0) >= 0.72 && (evaluationScore ?? 0) < 0.82) {
    blockers.push("evaluation_score_below_primary_gate");
  }
  if (readyModelCount > 0 && (evaluationScore ?? 0) >= 0.82 && (evaluationScore ?? 0) < 0.92) {
    blockers.push("evaluation_score_below_groq_retirement_gate");
  }

  const nextAction: AiCostReport["elyanModel"]["nextAction"] =
    activeTrainingJobs > 0
      ? "wait_for_active_training_job"
      : readySftDatasets <= 0
        ? "export_sft_ready_corrections_dataset"
        : readyModelCount <= 0
          ? "queue_elyan_model_refresh"
          : (evaluationScore ?? 0) >= 0.92
            ? "groq_retirement_candidate"
            : (evaluationScore ?? 0) >= 0.82
              ? "promote_elyan_primary_after_operator_review"
              : (evaluationScore ?? 0) >= 0.72
                ? "enable_canary_after_operator_review"
                : "run_shadow_evaluation";
  if (nextAction === "enable_canary_after_operator_review" && !canaryEnabled) {
    blockers.push("canary_flag_disabled");
  }
  if (
    (nextAction === "promote_elyan_primary_after_operator_review" ||
      nextAction === "groq_retirement_candidate") &&
    !primaryEnabled
  ) {
    blockers.push("primary_flag_disabled");
  }

  const recommendedCommand =
    nextAction === "export_sft_ready_corrections_dataset"
      ? "npm run brain:export-sft-corrections -- --write-jsonl=artifacts/brain-datasets/sft-corrections.jsonl"
      : nextAction === "queue_elyan_model_refresh"
        ? "npm run brain:queue-elyan-refresh -- --user-id=<uuid>"
        : nextAction === "wait_for_active_training_job"
          ? "npm run training:worker"
          : "npm run brain:elyan-promotion-preflight -- --user-id=<uuid>";
  const liveRoutingCandidate =
    (nextAction === "enable_canary_after_operator_review" && canaryEnabled) ||
    ((nextAction === "promote_elyan_primary_after_operator_review" ||
      nextAction === "groq_retirement_candidate") &&
      primaryEnabled);

  return {
    readyModelCount,
    activeTrainingJobs,
    queuedTrainingJobs: queuedJobs,
    readySftDatasets,
    compactEligibleDatasets,
    latestModel: {
      id: model?.latest_model_id ?? null,
      scope: model?.latest_model_scope ?? null,
      provider: model?.latest_model_provider ?? null,
      baseModel: model?.latest_base_model ?? null,
      adapterKind: model?.latest_adapter_kind ?? null,
      evaluationScore,
      qualityCompositeScore,
      promotionGate: model?.latest_promotion_gate ?? null,
      updatedAt: nullableIso(model?.latest_updated_at),
    },
    latestTrainingJob: {
      id: training?.latest_job_id ?? null,
      status: training?.latest_job_status ?? null,
      kind: training?.latest_job_kind ?? null,
      baseModel: training?.latest_job_base_model ?? null,
      updatedAt: nullableIso(training?.latest_job_updated_at),
    },
    latestSftDataset: {
      id: dataset?.latest_dataset_id ?? null,
      version: dataset?.latest_dataset_version ?? null,
      compactionQualityScore: nullableNumber(dataset?.latest_compaction_quality_score, { round: false }),
      updatedAt: nullableIso(dataset?.latest_dataset_updated_at),
    },
    nextAction,
    promotionFlags: {
      canaryEnabled,
      primaryEnabled,
    },
    liveRoutingCandidate,
    recommendedCommand,
    blockers: [...new Set(blockers)],
  };
}

function addWorkloadBucket(
  buckets: AiCostReport["providerInvocations"]["byWorkload"],
  workload: string,
  patch: {
    calls: number;
    totalTokens: number;
    errorCalls: number;
    fallbackCalls: number;
  },
): void {
  const current = buckets[workload] ?? {
    calls: 0,
    totalTokens: 0,
    errorCalls: 0,
    fallbackCalls: 0,
  };
  buckets[workload] = {
    calls: current.calls + patch.calls,
    totalTokens: current.totalTokens + patch.totalTokens,
    errorCalls: current.errorCalls + patch.errorCalls,
    fallbackCalls: current.fallbackCalls + patch.fallbackCalls,
  };
}

export function buildAiCostReport(input: {
  generatedAt: Date;
  windowHours: number;
  since: Date;
  providerRows: ProviderInvocationAggregateRow[];
  turnRows: TurnMetricAggregateRow[];
  modelRows?: ElyanModelReadinessRow[];
  trainingRows?: ElyanTrainingReadinessRow[];
  datasetRows?: ElyanDatasetReadinessRow[];
  canaryEnabled?: boolean;
  primaryEnabled?: boolean;
}): AiCostReport {
  const providerByWorkload: AiCostReport["providerInvocations"]["byWorkload"] = {};
  const providerByModel = input.providerRows.map((row) => {
    const calls = toNumber(row.call_count);
    const promptTokens = toNumber(row.prompt_tokens);
    const completionTokens = toNumber(row.completion_tokens);
    const totalTokens = toNumber(row.total_tokens);
    const errorCalls = row.status === "error" ? calls : 0;
    const fallbackCalls = row.status === "fallback" ? calls : 0;

    addWorkloadBucket(providerByWorkload, row.workload, {
      calls,
      totalTokens,
      errorCalls,
      fallbackCalls,
    });

    return {
      provider: row.provider,
      model: row.model,
      workload: row.workload,
      route: row.route,
      status: row.status,
      calls,
      promptTokens,
      completionTokens,
      totalTokens,
      avgLatencyMs: nullableNumber(row.avg_latency_ms),
      p95LatencyMs: nullableNumber(row.p95_latency_ms),
    };
  });

  const turnByWorkload = input.turnRows.map((row) => ({
    workload: row.workload,
    turns: toNumber(row.turn_count),
    avgTotalMs: nullableNumber(row.avg_total_ms),
    avgFirstDeltaMs: nullableNumber(row.avg_first_delta_ms),
    p95TotalMs: nullableNumber(row.p95_total_ms),
    modelCallCount: toNumber(row.model_call_count),
    reasoningPasses: toNumber(row.reasoning_passes),
    refinementAppliedCount: toNumber(row.refinement_applied_count),
    rateLimitedCount: toNumber(row.rate_limited_count),
    dedupedInflightCount: toNumber(row.deduped_inflight_count),
    cheapSocialTurnCount: toNumber(row.cheap_social_turn_count),
    zeroModelCallCount: toNumber(row.zero_model_call_count),
    singleModelCallCount: toNumber(row.single_model_call_count),
    multiModelPassCount: toNumber(row.multi_model_pass_count),
    dedupedCostBucketCount: toNumber(row.deduped_cost_bucket_count),
  }));

  return {
    generatedAt: input.generatedAt.toISOString(),
    windowHours: input.windowHours,
    since: input.since.toISOString(),
    providerInvocations: {
      totalCalls: providerByModel.reduce((sum, row) => sum + row.calls, 0),
      totalTokens: providerByModel.reduce((sum, row) => sum + row.totalTokens, 0),
      promptTokens: providerByModel.reduce((sum, row) => sum + row.promptTokens, 0),
      completionTokens: providerByModel.reduce((sum, row) => sum + row.completionTokens, 0),
      errorCalls: providerByModel
        .filter((row) => row.status === "error")
        .reduce((sum, row) => sum + row.calls, 0),
      fallbackCalls: providerByModel
        .filter((row) => row.status === "fallback")
        .reduce((sum, row) => sum + row.calls, 0),
      byWorkload: providerByWorkload,
      byModel: providerByModel.sort(
        (left, right) => right.totalTokens - left.totalTokens || right.calls - left.calls,
      ),
    },
    turnMetrics: {
      totalTurns: turnByWorkload.reduce((sum, row) => sum + row.turns, 0),
      modelCallCount: turnByWorkload.reduce((sum, row) => sum + row.modelCallCount, 0),
      reasoningPasses: turnByWorkload.reduce((sum, row) => sum + row.reasoningPasses, 0),
      refinementAppliedCount: turnByWorkload.reduce((sum, row) => sum + row.refinementAppliedCount, 0),
      rateLimitedCount: turnByWorkload.reduce((sum, row) => sum + row.rateLimitedCount, 0),
      dedupedInflightCount: turnByWorkload.reduce((sum, row) => sum + row.dedupedInflightCount, 0),
      cheapSocialTurnCount: turnByWorkload.reduce((sum, row) => sum + row.cheapSocialTurnCount, 0),
      zeroModelCallCount: turnByWorkload.reduce((sum, row) => sum + row.zeroModelCallCount, 0),
      singleModelCallCount: turnByWorkload.reduce((sum, row) => sum + row.singleModelCallCount, 0),
      multiModelPassCount: turnByWorkload.reduce((sum, row) => sum + row.multiModelPassCount, 0),
      dedupedCostBucketCount: turnByWorkload.reduce((sum, row) => sum + row.dedupedCostBucketCount, 0),
      byWorkload: turnByWorkload.sort((left, right) => right.turns - left.turns),
    },
    elyanModel: buildElyanModelReadiness({
      modelRows: input.modelRows,
      trainingRows: input.trainingRows,
      datasetRows: input.datasetRows,
      canaryEnabled: input.canaryEnabled,
      primaryEnabled: input.primaryEnabled,
    }),
  };
}

function readWindowHours(): number {
  const arg = process.argv.find((item) => item.startsWith("--hours="));
  const raw = arg ? arg.slice("--hours=".length) : process.env.AI_COST_REPORT_HOURS;
  const parsed = Number(raw ?? 24);
  return Number.isFinite(parsed) && parsed > 0 && parsed <= 24 * 31 ? parsed : 24;
}

async function main(): Promise<void> {
  try {
    process.loadEnvFile();
  } catch (error) {
    const code = typeof error === "object" && error && "code" in error ? String(error.code) : "";
    if (code !== "ENOENT") {
      throw error;
    }
  }

  const env = loadEnv();
  const windowHours = readWindowHours();
  const generatedAt = new Date();
  const since = new Date(generatedAt.getTime() - windowHours * 60 * 60 * 1000);
  const sql = postgres(env.DATABASE_URL, {
    prepare: false,
    max: 1,
    connect_timeout: env.DB_CONNECT_TIMEOUT_SECONDS,
    idle_timeout: env.DB_IDLE_TIMEOUT_SECONDS,
  });

  try {
    const providerRows = await sql<ProviderInvocationAggregateRow[]>`
      select
        provider::text as provider,
        model,
        workload,
        route,
        status::text as status,
        count(*)::int as call_count,
        coalesce(sum(prompt_tokens), 0)::int as prompt_tokens,
        coalesce(sum(completion_tokens), 0)::int as completion_tokens,
        coalesce(sum(total_tokens), 0)::int as total_tokens,
        avg(latency_ms)::float as avg_latency_ms,
        percentile_cont(0.95) within group (order by latency_ms)::float as p95_latency_ms
      from ai_provider_invocations
      where created_at >= ${since}
      group by provider, model, workload, route, status
      order by total_tokens desc, call_count desc
    `;

    const turnRows = await sql<TurnMetricAggregateRow[]>`
      select
        workload,
        count(*)::int as turn_count,
        avg(nullif(timings->>'total_ms', '')::float)::float as avg_total_ms,
        avg(nullif(timings->>'first_delta_ms', '')::float)::float as avg_first_delta_ms,
        percentile_cont(0.95) within group (
          order by nullif(timings->>'total_ms', '')::float
        )::float as p95_total_ms,
        coalesce(sum(coalesce(nullif(quality->>'model_call_count', '')::int, 0)), 0)::int as model_call_count,
        coalesce(sum(coalesce(nullif(quality->>'reasoning_passes', '')::int, 0)), 0)::int as reasoning_passes,
        count(*) filter (where quality->>'refinement_applied' = 'true')::int as refinement_applied_count,
        count(*) filter (where quality->>'rate_limited' = 'true')::int as rate_limited_count,
        count(*) filter (where quality->>'deduped_inflight' = 'true')::int as deduped_inflight_count,
        count(*) filter (where quality->>'cheap_social_turn' = 'true')::int as cheap_social_turn_count,
        count(*) filter (where quality->>'estimated_cost_bucket' = 'zero_model_call')::int as zero_model_call_count,
        count(*) filter (where quality->>'estimated_cost_bucket' = 'single_model_call')::int as single_model_call_count,
        count(*) filter (where quality->>'estimated_cost_bucket' = 'multi_model_pass')::int as multi_model_pass_count,
        count(*) filter (where quality->>'estimated_cost_bucket' = 'deduped_inflight')::int as deduped_cost_bucket_count
      from turn_metrics
      where created_at >= ${since}
      group by workload
      order by turn_count desc
    `;
    const modelRows = await sql<ElyanModelReadinessRow[]>`
      with latest_ready_model as (
        select
          id,
          scope::text as scope,
          provider,
          base_model,
          adapter_kind,
          metadata,
          updated_at
        from model_artifacts
        where status = 'ready'
          and storage_uri is not null
          and checksum is not null
        order by scope desc, updated_at desc
        limit 1
      )
      select
        (
          select count(*)::int
          from model_artifacts
          where status = 'ready'
            and storage_uri is not null
            and checksum is not null
        ) as ready_model_count,
        id::text as latest_model_id,
        scope as latest_model_scope,
        provider as latest_model_provider,
        base_model as latest_base_model,
        adapter_kind as latest_adapter_kind,
        nullif(metadata->>'evaluationScore', '')::float as latest_evaluation_score,
        nullif(metadata->>'qualityCompositeScore', '')::float as latest_quality_composite_score,
        metadata->>'promotionGate' as latest_promotion_gate,
        updated_at as latest_updated_at
      from latest_ready_model
      union all
      select
        0::int as ready_model_count,
        null::text as latest_model_id,
        null::text as latest_model_scope,
        null::text as latest_model_provider,
        null::text as latest_base_model,
        null::text as latest_adapter_kind,
        null::float as latest_evaluation_score,
        null::float as latest_quality_composite_score,
        null::text as latest_promotion_gate,
        null::timestamptz as latest_updated_at
      where not exists (select 1 from latest_ready_model)
      limit 1
    `;
    const trainingRows = await sql<ElyanTrainingReadinessRow[]>`
      with model_training_jobs as (
        select *
        from training_jobs
        where kind in ('sft', 'lora', 'dpo')
      ),
      latest_job as (
        select id, status::text as status, kind::text as kind, base_model, updated_at
        from model_training_jobs
        order by updated_at desc
        limit 1
      )
      select
        (select count(*)::int from model_training_jobs where status = 'queued') as queued_jobs,
        (select count(*)::int from model_training_jobs where status = 'running') as running_jobs,
        id::text as latest_job_id,
        status as latest_job_status,
        kind as latest_job_kind,
        base_model as latest_job_base_model,
        updated_at as latest_job_updated_at
      from latest_job
      union all
      select
        0::int as queued_jobs,
        0::int as running_jobs,
        null::text as latest_job_id,
        null::text as latest_job_status,
        null::text as latest_job_kind,
        null::text as latest_job_base_model,
        null::timestamptz as latest_job_updated_at
      where not exists (select 1 from latest_job)
      limit 1
    `;
    const datasetRows = await sql<ElyanDatasetReadinessRow[]>`
      with sft_ready as (
        select id, metadata, updated_at
        from dataset_manifests
        where status = 'ready'
          and metadata->>'datasetRole' = 'sft_ready_corrections_jsonl'
        order by updated_at desc
      ),
      latest_sft as (
        select id, metadata, updated_at
        from sft_ready
        limit 1
      )
      select
        (select count(*)::int from sft_ready) as sft_ready_dataset_count,
        (
          select count(*)::int
          from sft_ready
          where metadata->>'compactDatasetEligible' = 'true'
            or metadata->>'approvedCorrectionsOnly' = 'true'
        ) as compact_eligible_dataset_count,
        id::text as latest_dataset_id,
        metadata->>'datasetVersion' as latest_dataset_version,
        nullif(metadata->>'compactionQualityScore', '')::float as latest_compaction_quality_score,
        updated_at as latest_dataset_updated_at
      from latest_sft
      union all
      select
        0::int as sft_ready_dataset_count,
        0::int as compact_eligible_dataset_count,
        null::text as latest_dataset_id,
        null::text as latest_dataset_version,
        null::float as latest_compaction_quality_score,
        null::timestamptz as latest_dataset_updated_at
      where not exists (select 1 from latest_sft)
      limit 1
    `;

    console.log(
      JSON.stringify(
        buildAiCostReport({
          generatedAt,
          windowHours,
          since,
          providerRows,
          turnRows,
          modelRows,
          trainingRows,
          datasetRows,
          canaryEnabled: env.ELYAN_MODEL_CANARY_ENABLED,
          primaryEnabled: env.ELYAN_MODEL_PRIMARY_ENABLED,
        }),
        null,
        2,
      ),
    );
  } finally {
    await sql.end({ timeout: 5 });
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  void main().catch((error) => {
    console.error(
      JSON.stringify(
        {
          ok: false,
          error: error instanceof Error ? error.message : "ai_cost_report_failed",
        },
        null,
        2,
      ),
    );
    process.exitCode = 1;
  });
}
