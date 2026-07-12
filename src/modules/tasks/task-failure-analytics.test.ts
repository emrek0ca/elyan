import assert from "node:assert/strict";
import test from "node:test";
import {
  aggregateTaskFailures,
  deriveTaskFailureSignature,
  normalizeFailureCode,
} from "./task-failure-analytics.js";

test("normalizeFailureCode slugifies codes and free text, empty falls back to unknown", () => {
  assert.equal(normalizeFailureCode("WORK_ORDER_INVALID"), "work_order_invalid");
  assert.equal(normalizeFailureCode("Capability Not Ready!"), "capability_not_ready");
  assert.equal(normalizeFailureCode("   "), "unknown");
  assert.equal(normalizeFailureCode(null), "unknown");
});

test("deriveTaskFailureSignature reads error code and desktop capabilities", () => {
  const signature = deriveTaskFailureSignature({
    error: "WORK_ORDER_INVALID",
    payload: {
      desktopContext: { requiresCapabilities: ["open_app", "OPEN_APP", "play_media"] },
    },
  });
  assert.equal(signature.errorCode, "work_order_invalid");
  assert.equal(signature.failedTool, null);
  assert.deepEqual(signature.capabilities, ["open_app", "play_media"]);
});

test("deriveTaskFailureSignature infers unverified side effect when error is missing", () => {
  const signature = deriveTaskFailureSignature({
    result: {
      verification: {
        status: "failed",
        unverifiedSideEffects: ["email_send"],
      },
    },
    payload: {
      desktopWorkOrder: { requiredCapabilities: ["email_send"] },
    },
  });
  assert.equal(signature.errorCode, "unverified_side_effect");
  assert.equal(signature.failedTool, "email_send");
  assert.deepEqual(signature.capabilities, ["email_send"]);
});

test("deriveTaskFailureSignature falls back to result.error.code", () => {
  const signature = deriveTaskFailureSignature({
    result: { error: { code: "CAPABILITY_NOT_READY", message: "hazır değil" } },
  });
  assert.equal(signature.errorCode, "capability_not_ready");
  assert.deepEqual(signature.capabilities, []);
});

test("aggregateTaskFailures ranks codes by count with capability breakdown", () => {
  const rows = [
    { taskId: "t1", signature: { errorCode: "work_order_invalid", failedTool: null, capabilities: ["open_app"] } },
    { taskId: "t2", signature: { errorCode: "work_order_invalid", failedTool: null, capabilities: ["open_app", "play_media"] } },
    { taskId: "t3", signature: { errorCode: "capability_not_ready", failedTool: null, capabilities: ["whatsapp"] } },
  ];
  const aggregated = aggregateTaskFailures(rows);

  assert.equal(aggregated.length, 2);
  assert.equal(aggregated[0].errorCode, "work_order_invalid");
  assert.equal(aggregated[0].count, 2);
  assert.deepEqual(aggregated[0].sampleTaskIds, ["t1", "t2"]);
  assert.equal(aggregated[0].capabilities[0].capability, "open_app");
  assert.equal(aggregated[0].capabilities[0].count, 2);
  assert.equal(aggregated[1].errorCode, "capability_not_ready");
  assert.equal(aggregated[1].count, 1);
});

test("aggregateTaskFailures honors sampleLimit", () => {
  const rows = Array.from({ length: 8 }, (_value, index) => ({
    taskId: `t${index}`,
    signature: { errorCode: "unknown", failedTool: null, capabilities: [] },
  }));
  const aggregated = aggregateTaskFailures(rows, { sampleLimit: 3 });
  assert.equal(aggregated[0].count, 8);
  assert.equal(aggregated[0].sampleTaskIds.length, 3);
});
