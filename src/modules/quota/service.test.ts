import assert from "node:assert/strict";
import test from "node:test";
import { AppError } from "../../lib/errors.js";
import {
  assertAttachmentQuotaAllowedFromUsage,
  assertTrialTaskQuotaAllowedFromUsage,
  buildTrialQuotaWindows,
  getTrialQuotaPolicy,
  TRIAL_DAILY_LIMIT,
  TRIAL_FIVE_HOUR_LIMIT,
  TRIAL_WEEKLY_LIMIT,
  type TrialQuotaUsage,
} from "./service.js";

function buildQuotaUsage(overrides: Partial<TrialQuotaUsage> = {}): TrialQuotaUsage {
  return {
    identityId: "identity-1",
    planCode: "free",
    qualityProfile: "free_basic",
    dailyLimit: TRIAL_FIVE_HOUR_LIMIT,
    dailyUsed: 2,
    dailyRemaining: Math.max(0, TRIAL_FIVE_HOUR_LIMIT - 2),
    dailyResetAt: new Date("2030-01-02T10:00:00.000Z"),
    dailyProgressPercent: 89,
    weeklyLimit: TRIAL_WEEKLY_LIMIT,
    weeklyUsed: 10,
    weeklyRemaining: Math.max(0, TRIAL_WEEKLY_LIMIT - 10),
    weeklyResetAt: new Date("2030-01-08T10:00:00.000Z"),
    weeklyProgressPercent: 86,
    documentUploadLimit: 4,
    documentUploadCount: 1,
    documentUploadRemaining: 3,
    imageUploadLimit: 4,
    imageUploadCount: 1,
    imageUploadRemaining: 3,
    ...overrides,
  };
}

test("buildTrialQuotaWindows exposes the canonical backend quota windows", () => {
  const windows = buildTrialQuotaWindows(buildQuotaUsage());

  assert.equal(windows.length, 2);
  assert.equal(windows[0]?.type, "five_hour");
  assert.equal(windows[0]?.title, "5 Saatlik");
  assert.equal(windows[0]?.windowHours, 5);
  assert.equal(windows[0]?.remaining, TRIAL_FIVE_HOUR_LIMIT - 2);
  assert.equal(windows[1]?.type, "weekly");
  assert.equal(windows[1]?.title, "7 Günlük");
  assert.equal(windows[1]?.windowHours, 168);
  assert.equal(windows[1]?.remaining, TRIAL_WEEKLY_LIMIT - 10);
});

test("assertTrialTaskQuotaAllowedFromUsage fails closed when the 5-hour compute budget is exhausted", () => {
  assert.throws(
    () =>
      assertTrialTaskQuotaAllowedFromUsage(
        buildQuotaUsage({
          dailyUsed: TRIAL_FIVE_HOUR_LIMIT,
          dailyRemaining: 0,
        }),
      ),
    (error: unknown) => {
      assert.ok(error instanceof AppError);
      assert.equal(error.code, "five_hour_quota_reached");
      assert.equal(error.message, "5 saatlik kullanım hakkı doldu.");
      return true;
    },
  );
});

test("assertTrialTaskQuotaAllowedFromUsage fails closed when the weekly compute budget is exhausted", () => {
  assert.throws(
    () =>
      assertTrialTaskQuotaAllowedFromUsage(
        buildQuotaUsage({
          weeklyUsed: TRIAL_WEEKLY_LIMIT,
          weeklyRemaining: 0,
        }),
      ),
    (error: unknown) => {
      assert.ok(error instanceof AppError);
      assert.equal(error.code, "weekly_quota_reached");
      assert.equal(error.message, "Haftalık kullanım hakkı doldu.");
      return true;
    },
  );
});

test("assertAttachmentQuotaAllowedFromUsage blocks documents and images independently", () => {
  assert.throws(
    () =>
      assertAttachmentQuotaAllowedFromUsage(
        buildQuotaUsage({
          documentUploadCount: 4,
          documentUploadRemaining: 0,
        }),
        { requiredDocumentUploads: 1 },
      ),
    (error: unknown) => {
      assert.ok(error instanceof AppError);
      assert.equal(error.code, "document_quota_reached");
      return true;
    },
  );

  assert.throws(
    () =>
      assertAttachmentQuotaAllowedFromUsage(
        buildQuotaUsage({
          imageUploadCount: 4,
          imageUploadRemaining: 0,
        }),
        { requiredImageUploads: 1 },
      ),
    (error: unknown) => {
      assert.ok(error instanceof AppError);
      assert.equal(error.code, "image_quota_reached");
      return true;
    },
  );
});

test("getTrialQuotaPolicy exposes the stable identity quota contract", () => {
  const policy = getTrialQuotaPolicy();

  assert.equal(policy.mode, "identity_window");
  assert.equal(policy.source, "usage_records+quota_state");
  assert.equal(policy.commitPoint, "task.create+brain.inference");
  assert.equal(policy.consumptionMetric, "budget_units");
  assert.equal(policy.fiveHourWindowHours, 5);
  assert.equal(policy.dailyWindowHours, 5);
  assert.equal(policy.weeklyWindowHours, 168);
  assert.equal(policy.idempotency.scope, "identity");
  assert.equal(policy.idempotency.keyStrategy, "taskId+metric");
  assert.equal(policy.idempotency.singleWritePerTask, true);
  assert.deepEqual(policy.appliesTo, ["chat", "task", "document_upload", "image_upload"]);
  assert.deepEqual(policy.safeErrorCodes, [
    "five_hour_quota_reached",
    "daily_quota_reached",
    "weekly_quota_reached",
    "document_quota_reached",
    "image_quota_reached",
    "server_brain_unavailable",
  ]);
});
