import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { errorHandlerPlugin } from "../../plugins/error-handler.js";
import { runtimeRoutes } from "./routes.js";
import {
  runtimeSocketMessageSchema,
  runtimeTaskAckBodySchema,
} from "./schemas.js";

test("runtime register returns validation_error for invalid device identity payload", async () => {
  const app = Fastify();
  await app.register(errorHandlerPlugin);
  await app.register(runtimeRoutes, { prefix: "/v1/runtime" });

  const response = await app.inject({
    method: "POST",
    url: "/v1/runtime/register",
    payload: {
      deviceId: "desktop-ext-1",
      deviceSecret: "short",
      capabilities: [],
      capabilityStates: {},
    },
  });

  assert.equal(response.statusCode, 400);
  assert.equal(response.json().error, "validation_error");
  assert.equal(response.json().message, "Invalid request payload");
  assert.deepEqual(response.json().details, [
    { path: "deviceId", message: "Invalid uuid" },
    {
      path: "deviceSecret",
      message: "String must contain at least 16 character(s)",
    },
  ]);
  assert.equal(typeof response.json().requestId, "string");
  assert.equal(response.json().requestId.length > 0, true);

  await app.close();
});

test("runtime websocket ack schema accepts additive acceptedAt", () => {
  const parsed = runtimeSocketMessageSchema.parse({
    type: "task.ack",
    taskId: "11111111-1111-4111-8111-111111111111",
    leaseId: "lease-1",
    state: "accepted",
    acceptedAt: "2030-01-01T00:00:00.000Z",
    consumedContractFields: ["semanticGoal", "contextPack.outputContract"],
  });

  assert.equal(parsed.type, "task.ack");
  assert.equal(parsed.state, "accepted");
  assert.equal(parsed.acceptedAt, "2030-01-01T00:00:00.000Z");
  assert.deepEqual(parsed.consumedContractFields, [
    "semanticGoal",
    "contextPack.outputContract",
  ]);
});

test("runtime websocket ack schema accepts non-accepted work-order acceptance states", () => {
  const parsed = runtimeSocketMessageSchema.parse({
    type: "task.ack",
    taskId: "11111111-1111-4111-8111-111111111111",
    leaseId: "lease-1",
    state: "needs_permission",
    missingCapabilities: ["browser_control"],
    blockedReason: "screen permission missing",
    consumedContractFields: ["semanticDesktopContract"],
  });

  assert.equal(parsed.type, "task.ack");
  assert.equal(parsed.state, "needs_permission");
  assert.deepEqual(parsed.missingCapabilities, ["browser_control"]);
  assert.equal(parsed.blockedReason, "screen permission missing");
});

test("runtime task ack body schema accepts work-order acceptance details", () => {
  const parsed = runtimeTaskAckBodySchema.parse({
    leaseId: "lease-1",
    state: "missing_dependency",
    missingCapabilities: ["browser_control"],
    blockedReason: "browser adapter dependency is unavailable",
    consumedContractFields: [
      "semanticDesktopContract.requiredSemanticCapabilities",
    ],
  });

  assert.equal(parsed.leaseId, "lease-1");
  assert.equal(parsed.state, "missing_dependency");
  assert.deepEqual(parsed.missingCapabilities, ["browser_control"]);
  assert.equal(
    parsed.blockedReason,
    "browser adapter dependency is unavailable",
  );
  assert.deepEqual(parsed.consumedContractFields, [
    "semanticDesktopContract.requiredSemanticCapabilities",
  ]);
});

test("runtime websocket heartbeat schema accepts structured capability handshake", () => {
  const parsed = runtimeSocketMessageSchema.parse({
    type: "heartbeat",
    status: "online",
    capabilityHandshake: [
      {
        canonicalCapabilityId: "browser_control",
        adapter: "browser.control",
        ready: true,
        dependencyReady: true,
        permissionReady: false,
        aliases: ["browser.control"],
        version: "1.2.3",
        inputContractHash: "hash-browser-v1",
      },
    ],
  });

  assert.equal(parsed.type, "heartbeat");
  assert.equal(
    parsed.capabilityHandshake?.[0]?.canonicalCapabilityId,
    "browser_control",
  );
  assert.equal(parsed.capabilityHandshake?.[0]?.permissionReady, false);
});
