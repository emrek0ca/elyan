import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTurnMetricInputFromInference,
  recordTurnMetric,
} from "./turn-metrics.js";

function createAppMock(input: {
  onInsert?: (value: unknown) => void;
  failInsert?: boolean;
}) {
  const debugMessages: unknown[] = [];
  return {
    debugMessages,
    app: {
      db: {
        insert: () => ({
          values: async (value: unknown) => {
            if (input.failInsert) {
              throw new Error("db_down");
            }
            input.onInsert?.(value);
          },
        }),
      },
      log: {
        debug: (...args: unknown[]) => {
          debugMessages.push(args);
        },
      },
    },
  };
}

test("recordTurnMetric writes only normalized safe payload", async () => {
  let inserted: Record<string, unknown> | undefined;
  const { app } = createAppMock({
    onInsert: (value) => {
      inserted = value as Record<string, unknown>;
    },
  });

  await recordTurnMetric(app as never, {
    turnId: "task_123",
    userId: "11111111-1111-4111-8111-111111111111",
    sessionId: "22222222-2222-4222-8222-222222222222",
    workload: "mobile_chat_fast",
    timings: {
      total_ms: 123.4,
      first_delta_ms: 10.2,
      prompt: "private prompt",
    } as never,
    quality: {
      fallback_used: true,
      blocks_emitted: ["text"],
      model_call_count: 0,
      cheap_social_turn: true,
      estimated_cost_bucket: "zero_model_call",
      claim_confidence_avg: 0.74,
      uncertainty_action: "limit_answer",
      low_confidence_claims: 2,
      content: "private answer",
    } as never,
    prompt: "private prompt",
    content: "private answer",
  } as never);

  assert.ok(inserted);
  const row = inserted as Record<string, unknown>;
  assert.equal(row.turnId, "task_123");
  assert.equal(row.userId, "11111111-1111-4111-8111-111111111111");
  assert.equal(row.sessionId, "22222222-2222-4222-8222-222222222222");
  assert.equal(row.workload, "mobile_chat_fast");
  assert.deepEqual((row.timings as Record<string, unknown>).total_ms, 123);
  assert.deepEqual((row.timings as Record<string, unknown>).first_delta_ms, 10);
  assert.equal((row.timings as Record<string, unknown>).prompt, undefined);
  assert.deepEqual((row.quality as Record<string, unknown>).blocks_emitted, ["text"]);
  assert.equal((row.quality as Record<string, unknown>).model_call_count, 0);
  assert.equal((row.quality as Record<string, unknown>).cheap_social_turn, true);
  assert.equal(
    (row.quality as Record<string, unknown>).estimated_cost_bucket,
    "zero_model_call",
  );
  assert.equal((row.quality as Record<string, unknown>).claim_confidence_avg, 0.74);
  assert.equal((row.quality as Record<string, unknown>).uncertainty_action, "limit_answer");
  assert.equal((row.quality as Record<string, unknown>).low_confidence_claims, 2);
  assert.equal((row.quality as Record<string, unknown>).content, undefined);
  assert.equal(row.prompt, undefined);
  assert.equal(row.content, undefined);
});

test("recordTurnMetric swallows database failures", async () => {
  const { app, debugMessages } = createAppMock({ failInsert: true });

  await assert.doesNotReject(() =>
    recordTurnMetric(app as never, {
      turnId: "task_123",
      userId: "11111111-1111-4111-8111-111111111111",
      sessionId: null,
      workload: "mobile_chat_fast",
    }),
  );
  assert.equal(debugMessages.length, 1);
});

test("buildTurnMetricInputFromInference extracts safe metadata", () => {
  const metric = buildTurnMetricInputFromInference({
    userId: "11111111-1111-4111-8111-111111111111",
    taskId: "task_123",
    requestMetadata: {
      chat: { sessionId: "22222222-2222-4222-8222-222222222222" },
      prompt: "private prompt",
    },
    latencyMs: 250,
    metadata: {
      workload: "planning",
      firstDeltaMs: 42,
      completionLatencyMs: 210,
      turnEnvelopeParseOk: true,
      memoryOpsCount: 2,
      followUpsCount: 1,
      memoryForgetCount: 1,
      canonicalUserModelUsed: true,
      dialogueStateRevision: 4,
      staleRecallCount: 0,
      memoryRecallFactCount: 3,
      memoryRecallEpisodeCount: 2,
      toolLoopIterations: 3,
      toolMs: 77,
      reasoningPasses: 2,
      modelCallCount: 2,
      refinementApplied: true,
      rateLimited: true,
      dedupedInflight: true,
      cheapSocialTurn: false,
      estimatedCostBucket: "multi_model_pass",
      fallbackUsed: true,
      repairApplied: true,
      blocks: [{ type: "text" }, { type: "table" }, { type: "text" }],
      blockQuality: {
        metrics: {
          schemaInvalidBlockCount: 0,
          fallbackToTextCount: 1,
        },
      },
      renderRecipe: {
        metadata: {
          preflight_required: true,
          document_requirements: {
            must_include: ["Toplam 21.000 TL", "Metin cam Metin koca"],
            money_amounts: [{ raw: "21.000 TL", currency: "TRY" }],
            footer_text: "Metin cam Metin koca",
            spreadsheet: { include_totals: true },
          },
        },
      },
      dataInputBytes: 42_000,
      heavyContextTruncated: true,
      workerOffloaded: true,
      queueWaitMs: 19,
      agentEngineVersion: "agent_engine.v2",
      agentRunId: "run_123",
      agentRunState: "completed",
      claimConfidence: 0.73,
      lowConfidenceClaims: 2,
      uncertaintyAction: "limit_answer",
      toolCalledForUncertainty: false,
      clarificationRequested: true,
      missingEvidenceCount: 1,
      verifiedEvidenceCount: 2,
      contestedMemoryCount: 1,
      selfCheckApplied: true,
      content: "private answer",
    },
  });

  assert.equal(metric.turnId, "task_123");
  assert.equal(metric.sessionId, "22222222-2222-4222-8222-222222222222");
  assert.equal(metric.workload, "planning");
  assert.equal(metric.timings?.first_delta_ms, 42);
  assert.equal(metric.timings?.total_ms, 210);
  assert.equal(metric.timings?.tool_loop_iterations, 3);
  assert.equal(metric.timings?.tool_ms, 77);
  assert.equal(metric.quality?.envelope_parse_ok, true);
  assert.equal(metric.quality?.fallback_used, true);
  assert.equal(metric.quality?.salvage_used, true);
  assert.equal(metric.quality?.reasoning_passes, 2);
  assert.equal(metric.quality?.model_call_count, 2);
  assert.equal(metric.quality?.refinement_applied, true);
  assert.equal(metric.quality?.rate_limited, true);
  assert.equal(metric.quality?.deduped_inflight, true);
  assert.equal(metric.quality?.cheap_social_turn, false);
  assert.equal(metric.quality?.estimated_cost_bucket, "multi_model_pass");
  assert.equal(metric.quality?.memory_ops_count, 2);
  assert.equal(metric.quality?.follow_ups_count, 1);
  assert.equal(metric.quality?.memory_forget_count, 1);
  assert.equal(metric.quality?.canonical_user_model_used, true);
  assert.equal(metric.quality?.dialogue_state_revision, 4);
  assert.equal(metric.quality?.memory_recall_fact_count, 3);
  assert.equal(metric.quality?.memory_recall_episode_count, 2);
  assert.equal(metric.quality?.block_schema_valid, true);
  assert.equal(metric.quality?.block_fallback_used, true);
  assert.equal(metric.quality?.render_recipe_preflight_ok, true);
  assert.equal(metric.quality?.document_requirements_count, 5);
  assert.equal(metric.quality?.data_input_bytes_bucket, "le_64kb");
  assert.equal(metric.quality?.heavy_context_truncated, true);
  assert.equal(metric.quality?.worker_offloaded, true);
  assert.equal(metric.quality?.queue_wait_ms, 19);
  assert.equal(metric.quality?.agent_engine_version, "agent_engine.v2");
  assert.equal(metric.quality?.agent_run_state, "completed");
  assert.equal(metric.quality?.agent_verification_passed, true);
  assert.equal(metric.quality?.claim_confidence_avg, 0.73);
  assert.equal(metric.quality?.low_confidence_claims, 2);
  assert.equal(metric.quality?.uncertainty_action, "limit_answer");
  assert.equal(metric.quality?.tool_called_for_uncertainty, false);
  assert.equal(metric.quality?.clarification_requested, true);
  assert.equal(metric.quality?.missing_evidence_count, 1);
  assert.equal(metric.quality?.verified_evidence_count, 2);
  assert.equal(metric.quality?.contested_memory_count, 1);
  assert.equal(metric.quality?.claim_self_check_applied, true);
  assert.deepEqual(metric.quality?.blocks_emitted, ["text", "table"]);
  assert.equal((metric as Record<string, unknown>).content, undefined);
});
