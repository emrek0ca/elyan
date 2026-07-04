import assert from "node:assert/strict";
import test from "node:test";
import {
  buildApprovedCorrectionDatasetExport,
  exportSftReadyCorrectionsDataset,
  getApprovedCorrectionDatasetState,
} from "./review.js";

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

class FakeInsertBuilder {
  private currentValues: Record<string, unknown> = {};

  constructor(private readonly inserted: Array<Record<string, unknown>>) {}

  values(values: Record<string, unknown>) {
    this.currentValues = values;
    this.inserted.push(values);
    return this;
  }

  returning() {
    return Promise.resolve([
      {
        id: this.currentValues.name === "Elyan SFT-ready approved corrections export" ? "dataset-sft-1" : "inserted-1",
        createdAt: new Date("2030-01-04T00:00:00.000Z"),
        updatedAt: new Date("2030-01-04T00:00:00.000Z"),
        ...this.currentValues,
      },
    ]);
  }

  then<TResult1 = unknown[], TResult2 = never>(
    resolve?: ((value: unknown[]) => TResult1 | PromiseLike<TResult1>) | null,
    reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
  ) {
    return Promise.resolve([] as unknown[]).then(resolve, reject);
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

function makeApprovedLearningEvent(input: Parameters<typeof makeApprovedReview>[0]) {
  const approved = makeApprovedReview(input);
  return {
    id: input.id,
    userId: "user-1",
    accountId: "user-1",
    taskId: null,
    type: "brain_interaction",
    key: "response_scored",
    value: input.modelResponse,
    confidence: Math.round(input.evaluatorScore * 100),
    scope: "user",
    source: "brain_eval",
    privacyLevel: "safe",
    metadata: {
      reviewedBy: "reviewer-1",
      reviewedAt: input.reviewedAt,
      review: approved.review,
      approvalState: "approved",
      approvedByHuman: true,
      correctedAnswer: input.correctedAnswer,
    },
    expiresAt: null,
    createdAt: new Date(input.reviewedAt),
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

test("exportSftReadyCorrectionsDataset creates a safe manifest from approved corrections", async () => {
  const inserted: Array<Record<string, unknown>> = [];
  const app = {
    db: {
      select() {
        return new FakeSelectQuery([
          makeApprovedLearningEvent({
            id: "event-1",
            prompt: "Kısa cevap ver ve mevcut mimariyi bozma.",
            modelResponse: "Uzun bir cevap verelim.",
            correctedAnswer: "Kısa cevap ver; mevcut mimariyi bozma.",
            evaluatorScore: 0.92,
            boundaryScore: 0.9,
            reviewedAt: "2030-01-03T00:00:00.000Z",
          }),
        ]);
      },
      insert() {
        return new FakeInsertBuilder(inserted);
      },
    },
  };

  const result = await exportSftReadyCorrectionsDataset(app as never, {
    actorUserId: "admin-1",
    requestId: "req-export",
  });

  const manifestInsert = inserted.find((entry) => entry.name === "Elyan SFT-ready approved corrections export");
  assert.ok(manifestInsert);
  assert.equal(result.manifest?.id, "dataset-sft-1");
  assert.equal(result.manifest?.recordCount, 1);
  assert.equal(result.manifest?.format, "instruction_jsonl");
  assert.equal((manifestInsert.metadata as Record<string, unknown>).datasetRole, "sft_ready_corrections_jsonl");
  assert.equal((manifestInsert.metadata as Record<string, unknown>).approvedCorrectionsOnly, true);
  assert.equal((manifestInsert.metadata as Record<string, unknown>).sourceLineage, "approved_corrections");
  assert.equal((manifestInsert.metadata as Record<string, unknown>).compactDatasetEligible, true);

  const [line] = result.jsonl.trim().split("\n").map((item) => JSON.parse(item) as Record<string, unknown>);
  assert.equal(line.instruction, "Follow Elyan Constitution and return the corrected bounded answer.");
  assert.equal(line.expected_output, "Kısa cevap ver; mevcut mimariyi bozma.");
  assert.equal("modelResponse" in line, false);
  assert.equal("prompt" in line, false);
  assert.equal((line.dataset_quality as Record<string, unknown>).sourceLineage, "approved_corrections");

  const auditInsert = inserted.find((entry) => entry.action === "brain.dataset.export");
  assert.ok(auditInsert);
  assert.equal((auditInsert.payload as Record<string, unknown>).datasetRole, "sft_ready_corrections_jsonl");
});

test("exportSftReadyCorrectionsDataset keeps empty exports draft so training cannot consume them", async () => {
  const inserted: Array<Record<string, unknown>> = [];
  const app = {
    db: {
      select() {
        return new FakeSelectQuery([]);
      },
      insert() {
        return new FakeInsertBuilder(inserted);
      },
    },
  };

  const result = await exportSftReadyCorrectionsDataset(app as never, {
    actorUserId: "admin-1",
    requestId: "req-empty-export",
  });

  assert.equal(result.manifest?.status, "draft");
  assert.equal(result.manifest?.recordCount, 0);
  assert.equal(result.jsonl, "");
  const manifestInsert = inserted.find((entry) => entry.name === "Elyan SFT-ready approved corrections export");
  assert.equal(manifestInsert?.status, "draft");
  assert.equal((manifestInsert?.metadata as Record<string, unknown>).compactDatasetEligible, false);
});
