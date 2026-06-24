import assert from "node:assert/strict";
import test from "node:test";
import { buildApprovedCorrectionDatasetExport, getApprovedCorrectionDatasetState } from "./review.js";

class FakeSelectQuery<T> {
  constructor(private readonly result: T) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  then<TResult1 = T, TResult2 = never>(
    resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve(this.result).then(resolve, reject);
  }
}

function makeApprovedReview(input: {
  id: string;
  prompt: string;
  modelResponse: string;
  correctedAnswer: string;
  evaluatorScore: number;
  boundaryScore: number;
  reviewedAt: string;
}) {
  return {
    row: {
      id: input.id,
      metadata: {
        reviewedBy: "reviewer-1",
        reviewedAt: input.reviewedAt,
      },
    } as never,
    review: {
      prompt: input.prompt,
      promptPreview: input.prompt.slice(0, 140),
      modelResponse: input.modelResponse,
      routeDecision: {
        route: "server_brain",
      },
      expectedBehavior: "correct and bounded",
      evaluatorScore: input.evaluatorScore,
      boundaryScore: input.boundaryScore,
      failureType: "incorrect_answer",
      correctedAnswer: input.correctedAnswer,
      approvedByHuman: true,
      approvalState: "approved",
      answerSource: "model",
      gateRuleIds: ["boundary_guard"],
      boundaryOutcome: "blocked",
      selectedProfile: "mobile_chat_fast",
      latencyMs: 120,
      toolCalls: [],
      success: false,
      constitutionVersion: "v1",
      promptProfileVersion: "v1",
    } as never,
  };
}

test("buildApprovedCorrectionDatasetExport compacts approved corrections and carries quality metadata", () => {
  const now = new Date("2030-01-04T00:00:00.000Z");
  const exported = buildApprovedCorrectionDatasetExport(
    [
      makeApprovedReview({
        id: "1",
        prompt: "Fix the auth flow",
        modelResponse: "Use the old flow",
        correctedAnswer: "Use the guarded flow",
        evaluatorScore: 0.86,
        boundaryScore: 0.81,
        reviewedAt: "2030-01-01T00:00:00.000Z",
      }),
      makeApprovedReview({
        id: "2",
        prompt: "Fix the auth flow",
        modelResponse: "Use the old flow",
        correctedAnswer: "Use the guarded flow",
        evaluatorScore: 0.95,
        boundaryScore: 0.94,
        reviewedAt: "2030-01-03T00:00:00.000Z",
      }),
      makeApprovedReview({
        id: "3",
        prompt: "Improve memory ranking",
        modelResponse: "Keep all entries",
        correctedAnswer: "Prefer verified and pinned entries.",
        evaluatorScore: 0.91,
        boundaryScore: 0.9,
        reviewedAt: "2030-01-02T00:00:00.000Z",
      }),
    ],
    "sft_ready_corrections_compact_v1",
    now,
  );

  assert.equal(exported.records.length, 2);
  assert.equal(exported.summary.approvedCorrectionCount, 3);
  assert.equal(exported.summary.compactedRecordCount, 2);
  assert.equal(exported.summary.sourceLineage, "approved_corrections");
  assert.equal(exported.summary.compactDatasetEligible, true);
  assert.equal(exported.summary.compactionQualityScore >= 0.7, true);
  assert.equal(exported.records[0]?.row.id, "2");
  assert.equal(exported.records[0]?.compactedRank, 1);
});

test("getApprovedCorrectionDatasetState exposes additive compaction metadata", async () => {
  const app = {
    db: {
      select() {
        return new FakeSelectQuery([
          {
            id: "dataset-1",
            status: "ready",
            metadata: {
              datasetRole: "sft_ready_corrections_jsonl",
              datasetVersion: "dataset-v2",
              approvedCorrectionsOnly: true,
              sourceLineage: "approved_corrections",
              compactionMode: "sft_ready_corrections_compact_v1",
              approvedCorrectionCount: 3,
              compactedRecordCount: 2,
              freshSignalCount: 2,
              correctionDensity: 0.6667,
              freshSignalRatio: 1,
              signalFreshnessScore: 0.8432,
              lineageScore: 1,
              compactionQualityScore: 0.8221,
              compactDatasetEligible: true,
              freshnessWindowDays: 21,
              highSignalThreshold: 0.75,
              latestApprovedAt: "2030-01-03T00:00:00.000Z",
              oldestApprovedAt: "2030-01-02T00:00:00.000Z",
            },
          },
        ]);
      },
    },
  };

  const state = await getApprovedCorrectionDatasetState(app as never);

  assert.equal(state.ready, true);
  assert.equal(state.datasetVersion, "dataset-v2");
  assert.equal(state.compactionMode, "sft_ready_corrections_compact_v1");
  assert.equal(state.compactDatasetEligible, true);
  assert.equal(state.compactionQualityScore, 0.8221);
  assert.equal(state.approvedCorrectionCount, 3);
  assert.equal(state.compactedRecordCount, 2);
});
