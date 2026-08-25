import assert from "node:assert/strict";
import test from "node:test";
import {
  stepShapesFromTrajectory,
  taskEpisodeContractDigest,
} from "./episode-store.js";
import type { AgentTrajectoryRecord } from "./agent-trajectory.js";

function trajectory(
  overrides: Partial<AgentTrajectoryRecord> = {},
): AgentTrajectoryRecord {
  return {
    contract: "elyan.agent_trajectory.v1",
    version: 1,
    episodeId: "ep-1",
    taskId: "task-1",
    request: {
      contentIncluded: false,
      summary: "redacted",
      sha256: "a".repeat(64),
      lengthBucket: "short",
      language: "tr",
    },
    platform: {
      targetKind: "desktop",
      platform: "darwin",
      targetDeviceIdSha256: null,
      onlineAtAdmission: true,
      liveCapabilities: [],
    },
    modelDecision: {
      route: "desktop_runtime",
      intent: "system_observation",
      targetDevice: null,
      confidence: 0.9,
      requiredCapabilities: [],
      missingInformation: { present: false, sha256: null },
      requiresConfirmation: false,
      goalContract: {
        objectiveSha256: null,
        constraintsCount: 0,
        successCriteriaCount: 0,
        ambiguityPolicy: null,
      },
      provider: null,
      model: null,
      artifactVersion: null,
      decisionSource: null,
    },
    plan: { source: "compiled", revision: 1, steps: [] },
    toolCalls: [],
    approval: { required: false, capabilities: [], decision: "not_required" },
    verification: {
      status: "passed",
      evidenceKinds: ["tool_result"],
      evidenceCount: 1,
      explicit: true,
    },
    replanning: { occurred: false, count: 0, reasons: [] },
    outcome: { verdict: "fulfilled", reasons: [] },
    telemetry: { latencyMs: 120, retryCount: 0, errorCodes: [] },
    privacy: {
      rawPromptIncluded: false,
      rawToolResultsIncluded: false,
      rawToolArgsIncluded: false,
      redaction: "hash_only_default",
      trainingEligible: true,
      preferenceScope: "user",
    },
    ...overrides,
  } as AgentTrajectoryRecord;
}

test("adım şekli capability ve argüman ANAHTARLARINI taşır, değerleri taşımaz", () => {
  const shapes = stepShapesFromTrajectory(
    trajectory({
      plan: {
        source: "compiled",
        revision: 1,
        steps: [
          {
            sequence: 1,
            id: "s1",
            device: "desktop",
            capability: "sys_info",
            dependsOn: [],
            args: { query: "battery", secretToken: "abc123" },
            redactedArgKeys: [],
          },
        ],
      },
    }),
  );

  assert.deepEqual(shapes, [
    { capability: "sys_info", device: "desktop", argKeys: ["query", "secretToken"] },
  ]);
  // Değerler hiçbir alanda görünmemeli.
  assert.equal(JSON.stringify(shapes).includes("battery"), false);
  assert.equal(JSON.stringify(shapes).includes("abc123"), false);
});

test("plan adımı yoksa gerçekten çağrılan araçlar epizodun şeklidir", () => {
  const shapes = stepShapesFromTrajectory(
    trajectory({
      plan: { source: "dynamic", revision: null, steps: [] },
      toolCalls: [
        {
          sequence: 1,
          tool: "directory_tree",
          args: { path: "/x" },
          redactedArgKeys: [],
          ok: true,
          verified: true,
          attempt: 1,
          latencyMs: 20,
          errorCode: null,
          result: {
            contentIncluded: false,
            outputKind: null,
            resultSha256: null,
            stateReadbackObserved: null,
            stateReadbackKeys: [],
          },
        },
      ],
    }),
  );

  assert.deepEqual(shapes, [
    { capability: "directory_tree", device: null, argKeys: ["path"] },
  ]);
});

test("imza argüman DEĞERİNDEN bağımsız, adım sırasına bağlıdır", () => {
  const a = taskEpisodeContractDigest([
    { capability: "web_research", device: null, argKeys: ["query"] },
    { capability: "document_write", device: "desktop", argKeys: ["path", "content"] },
  ]);
  const sameShapeDifferentOrderOfKeys = taskEpisodeContractDigest([
    { capability: "web_research", device: null, argKeys: ["query"] },
    { capability: "document_write", device: "desktop", argKeys: ["content", "path"] },
  ]);
  const differentStepOrder = taskEpisodeContractDigest([
    { capability: "document_write", device: "desktop", argKeys: ["path", "content"] },
    { capability: "web_research", device: null, argKeys: ["query"] },
  ]);

  assert.equal(a, sameShapeDifferentOrderOfKeys);
  assert.notEqual(a, differentStepOrder);
  assert.equal(taskEpisodeContractDigest([]), null);
});
