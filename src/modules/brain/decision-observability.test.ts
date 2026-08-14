import assert from "node:assert/strict";
import test from "node:test";
import {
  buildBrainDecisionObservation,
  logBrainDecisionObservation,
} from "./decision-observability.js";

test("brain decision observation keeps queued task ids and route fields content-free", () => {
  const observation = buildBrainDecisionObservation({
    taskId: null,
    workload: "mobile_chat_fast",
    route: "server_brain",
    model: null,
    responseFormat: "text",
    result: "queued",
    durationMs: 12.8,
  });

  assert.deepEqual(observation, {
    task_id: null,
    workload: "mobile_chat_fast",
    route: "server_brain",
    model: null,
    response_format: "text",
    result: "queued",
    duration_ms: 12,
  });
  assert.equal("prompt" in observation, false);
});

test("brain decision observation includes the typed contract without user text", () => {
  const observation = buildBrainDecisionObservation({
    taskId: "task-1",
    workload: "document_generate",
    route: "server_brain",
    model: "model-a",
    responseFormat: "json_object",
    result: "running",
    durationMs: 1,
    semanticContract: {
      schemaVersion: "elyan.semantic_contract.v1",
      conversationMode: "chat",
      surface: "server_brain",
      intent: "create",
      artifact: "document",
      requiredContext: ["none"],
      sideEffect: "none",
      privacyClass: "public",
      requiredCapabilities: ["document.write"],
      needsApproval: false,
      confidence: 0.9,
      ambiguity: 0.02,
      evidence: ["artifact:document"],
    },
  });

  assert.deepEqual(observation.semantic_contract, {
    schema_version: "elyan.semantic_contract.v1",
    conversation_mode: "chat",
    surface: "server_brain",
    intent: "create",
    artifact: "document",
    required_context: ["none"],
    side_effect: "none",
    privacy_class: "public",
    required_capabilities: ["document.write"],
    needs_approval: false,
    confidence: 0.9,
    ambiguity: 0.02,
    evidence: ["artifact:document"],
  });
});

test("brain decision observation logs a single structured decision event", () => {
  const events: unknown[][] = [];
  const app = {
    log: {
      info: (...args: unknown[]) => {
        events.push(args);
      },
    },
  };

  logBrainDecisionObservation(app as never, {
    taskId: null,
    workload: "mobile_chat_fast",
    route: "server_brain",
    model: null,
    responseFormat: "text",
    result: "queued",
    durationMs: 3,
  });

  assert.equal(events.length, 1);
  assert.equal(events[0]?.[1], "brain decision");
});
