import assert from "node:assert/strict";
import test from "node:test";
import {
  AGENT_TRAJECTORY_CONTRACT,
  agentTrajectoryEpisodeId,
  buildAgentTrajectoryRecord,
} from "./agent-trajectory.js";

const task = {
  id: "00000000-0000-4000-8000-000000000101",
  userId: "00000000-0000-4000-8000-000000000102",
  targetDeviceId: "00000000-0000-4000-8000-000000000103",
  title: "Music kapat",
  payload: {
    prompt: "Music kapat; parola sk-live-secret-value-123456789",
    metadata: {
      routeDecision: {
        route: "desktop_runtime",
        intent: "screen_action",
        confidence: 0.94,
        capabilities: ["close_app"],
        requiresApproval: true,
      },
      runtimeCapabilitySnapshot: {
        platform: "macos",
        kind: "desktop",
        online: true,
        capabilities: ["close_app", "runtime.status"],
      },
    },
    desktopWorkOrder: {
      requiresApproval: true,
      approvalCapabilities: ["close_app"],
      semanticGoal: {
        objective: "Music uygulamasını kapat",
        constraints: ["Özel not: parola sk-live-secret-value-123456789"],
        successCriteria: ["Music işlemi artık çalışmıyor"],
        ambiguityPolicy: "ask",
      },
      planPreview: {
        planSource: "deterministic_registry",
        privacyClass: "side_effect",
        steps: [
          {
            id: "close_music",
            capability: "close_app",
            args: { app_name: "Music", password: "sk-live-secret-value-123456789" },
          },
        ],
      },
    },
    taskExecutionContract: {
      planRevision: 2,
      goal: {
        objective: "Music uygulamasını kapat",
        constraints: [],
        successCriteria: ["Music kapalı"],
        ambiguityPolicy: "ask",
      },
      execution: {
        steps: [
          {
            id: "close_music",
            device: "desktop",
            capability: "close_app",
            args: { app_name: "Music" },
            dependsOn: [],
          },
        ],
      },
      approval: { required: true, scope: ["close_app"] },
    },
  },
  result: {
    toolEvents: [
      {
        tool: "close_app",
        args: { app_name: "Music", message_body: "private message body" },
        ok: true,
        verified: true,
        attempt: 1,
        latencyMs: 42,
        output: { summary: "Music kapatıldı", secret: "sk-live-secret-value-123456789" },
        stateReadback: { observed: true, app: "Music", closed: true },
      },
    ],
    verification: {
      status: "passed",
      evidence: [{ kind: "state_readback", value: "private process output" }],
    },
    provider: "hosted",
    model: "planner-model",
    artifactVersion: "artifact-v1",
  },
  approvalRequest: {
    kind: "desktop_capability",
    resolution: { approved: true, status: "approved" },
  },
  error: null,
  createdAt: new Date("2026-08-23T10:00:00.000Z"),
  completedAt: new Date("2026-08-23T10:00:01.000Z"),
};

test("trajectory is deterministic, structured, and linked to the task", () => {
  const record = buildAgentTrajectoryRecord({
    task,
    result: task.result,
    assessment: { verdict: "fulfilled", reasons: [] },
  });

  assert.equal(record.contract, AGENT_TRAJECTORY_CONTRACT);
  assert.equal(record.episodeId, agentTrajectoryEpisodeId(task.id));
  assert.equal(record.request.contentIncluded, false);
  assert.equal(record.request.summary, "redacted");
  assert.equal(record.platform.platform, "macos");
  assert.deepEqual(record.platform.liveCapabilities, ["close_app", "runtime.status"]);
  assert.equal(record.modelDecision.route, "desktop_runtime");
  assert.equal(record.modelDecision.confidence, 0.94);
  assert.equal(record.plan.steps[0]?.capability, "close_app");
  assert.equal(record.toolCalls[0]?.verified, true);
  assert.equal(record.approval.decision, "approved");
  assert.equal(record.verification.status, "passed");
  assert.equal(record.privacy.trainingEligible, true);
});

test("trajectory never serializes prompt, secret, message body, or tool output", () => {
  const record = buildAgentTrajectoryRecord({
    task,
    result: task.result,
    assessment: { verdict: "fulfilled", reasons: [] },
  });
  const serialized = JSON.stringify(record);

  assert.equal(serialized.includes("sk-live-secret-value-123456789"), false);
  assert.equal(serialized.includes("private message body"), false);
  assert.equal(serialized.includes("private process output"), false);
  assert.equal(serialized.includes("Music kapat; parola"), false);
  assert.equal(serialized.includes("contentIncluded\\\":true"), false);
  const redactedBody = record.toolCalls[0]?.args.message_body as { kind?: string } | undefined;
  assert.equal(redactedBody?.kind, "redacted");
  assert.equal(record.toolCalls[0]?.result.contentIncluded, false);
});

test("unfulfilled trajectories cannot enter global training eligibility", () => {
  const record = buildAgentTrajectoryRecord({
    task: { ...task, error: "CAPABILITY_SCOPE_MISMATCH: private detail" },
    result: { toolEvents: [{ tool: "close_app", ok: false, errorCode: "APP_NOT_FOUND" }] },
    assessment: { verdict: "unfulfilled", reasons: ["error:private detail"] },
  });

  assert.equal(record.outcome.verdict, "unfulfilled");
  assert.equal(record.privacy.trainingEligible, false);
  assert.deepEqual(record.outcome.reasons, ["error_present"]);
  assert.deepEqual(record.telemetry.errorCodes, ["CAPABILITY_SCOPE_MISMATCH", "APP_NOT_FOUND"]);
});

test("side effects without approval and explicit evidence stay out of training", () => {
  const record = buildAgentTrajectoryRecord({
    task: {
      ...task,
      approvalRequest: { kind: "desktop_capability" },
    },
    result: {
      toolEvents: [{ tool: "close_app", ok: true }],
      verification: { status: "passed", evidence: [] },
    },
    assessment: { verdict: "fulfilled", reasons: [] },
  });

  assert.equal(record.approval.decision, "unknown");
  assert.equal(record.verification.evidenceCount, 0);
  assert.equal(record.privacy.trainingEligible, false);
});
