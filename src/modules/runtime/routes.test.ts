import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { errorHandlerPlugin } from "../../plugins/error-handler.js";
import { runtimeRoutes } from "./routes.js";
import { runtimeSocketMessageSchema } from "./schemas.js";

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
    acceptedAt: "2030-01-01T00:00:00.000Z",
  });

  assert.equal(parsed.type, "task.ack");
  assert.equal(parsed.acceptedAt, "2030-01-01T00:00:00.000Z");
});
