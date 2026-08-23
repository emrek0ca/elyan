import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";
import {
  buildContinuousLearningDatasetCandidate,
  getContinuousLearningDailyWindow,
} from "./continuous-learning-pipeline.js";

function event(overrides: Partial<{
  id: string;
  userId: string;
  taskId: string | null;
  type: string;
  key: string;
  value: string;
  confidence: number;
  scope: string;
  source: string;
  privacyLevel: string;
  metadata: Record<string, unknown>;
  expiresAt: Date | null;
  createdAt: Date;
}> = {}) {
  return {
    id: overrides.id ?? randomUUID(),
    userId: overrides.userId ?? "00000000-0000-4000-8000-000000000001",
    taskId: overrides.taskId ?? null,
    type: overrides.type ?? "task_feedback",
    key: overrides.key ?? "success_trace",
    value: overrides.value ?? JSON.stringify({ outcome: "success", route: "server_brain" }),
    confidence: overrides.confidence ?? 84,
    // Ordinary fixture events model the already-approved shared corpus. User
    // scoped events are covered explicitly below because they now require an
    // opt-in marker for global training.
    scope: overrides.scope ?? "shared",
    source: overrides.source ?? "task_feedback",
    privacyLevel: overrides.privacyLevel ?? "safe",
    metadata: overrides.metadata ?? { approvedByHuman: true },
    expiresAt: overrides.expiresAt ?? null,
    createdAt: overrides.createdAt ?? new Date("2026-07-04T12:00:00.000Z"),
  };
}

test("continuous learning candidate filters private values and never exports raw event text", () => {
  const candidate = buildContinuousLearningDatasetCandidate(
    [
      event({ id: "00000000-0000-4000-8000-000000000010", value: "good correction signal" }),
      event({
        id: "00000000-0000-4000-8000-000000000011",
        value: "my email is user@example.com",
      }),
      event({
        id: "00000000-0000-4000-8000-000000000012",
        privacyLevel: "private",
        value: "private prompt content",
      }),
      event({
        id: "00000000-0000-4000-8000-000000000013",
        metadata: { trainingEligible: false },
        value: "forgotten preference",
      }),
    ],
    { now: new Date("2026-07-05T00:00:00.000Z"), replayRatio: 20 },
  );

  assert.equal(candidate.acceptedEventCount, 1);
  assert.equal(candidate.rejectedEventCount, 3);
  assert.equal(candidate.privacyReport.sensitiveRejectedCount, 1);
  assert.equal(candidate.privacyReport.privacyRejectedCount, 1);
  assert.equal(candidate.privacyReport.rawEventValuesIncluded, false);
  assert.equal(candidate.privacyReport.promptContentIncluded, false);
  const serialized = JSON.stringify(candidate);
  assert.equal(serialized.includes("user@example.com"), false);
  assert.equal(serialized.includes("private prompt content"), false);
});

test("continuous learning candidate dedupes content and adds replay records", () => {
  const candidate = buildContinuousLearningDatasetCandidate(
    [
      event({ id: "00000000-0000-4000-8000-000000000020", value: "same useful trace" }),
      event({ id: "00000000-0000-4000-8000-000000000021", value: "same useful trace" }),
      event({ id: "00000000-0000-4000-8000-000000000022", value: "another useful trace" }),
    ],
    { now: new Date("2026-07-05T00:00:00.000Z"), replayRatio: 25 },
  );

  assert.equal(candidate.acceptedEventCount, 2);
  assert.equal(candidate.dedupedEventCount, 1);
  assert.equal(candidate.rejectedEventCount, 0);
  assert.equal(candidate.replayRecordCount, 1);
  assert.equal(candidate.replayReport.policy, "preserve_previous_capabilities");
});

test("continuous learning daily window uses the previous complete UTC day", () => {
  const window = getContinuousLearningDailyWindow(new Date("2026-07-05T21:20:00.000Z"));
  assert.equal(window.windowStart.toISOString(), "2026-07-04T00:00:00.000Z");
  assert.equal(window.windowEnd.toISOString(), "2026-07-05T00:00:00.000Z");
});

test("user-scoped events require explicit global training opt-in", () => {
  const candidate = buildContinuousLearningDatasetCandidate([
    event({ id: "00000000-0000-4000-8000-000000000030", scope: "user" }),
    event({
      id: "00000000-0000-4000-8000-000000000031",
      scope: "user",
      metadata: { approvedByHuman: true, globalTrainingEligible: true },
    }),
  ]);

  assert.equal(candidate.acceptedEventCount, 1);
  assert.equal(candidate.privacyReport.rejectedByReason.scope_not_global_eligible, 1);
});
