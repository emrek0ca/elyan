import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { errorHandlerPlugin } from "../../plugins/error-handler.js";
import {
  acquireRealtimeStreamSlot,
  activeRealtimeStreamCountForUser,
  createSsePendingWriteState,
  realtimeStreamChannelForUser,
  realtimeRoutes,
  shapeRealtimeEventEnvelope,
  shouldDropSlowSseClient,
  shouldDropSsePendingWrite,
  shouldDispatchAssignedRuntimeTask,
} from "./routes.js";

test("realtime stream defaults mobile clients to the user channel", () => {
  assert.equal(realtimeStreamChannelForUser("user-1", {}), "user:user-1");
});

test("realtime stream keeps explicit task and device scopes opt-in", () => {
  assert.equal(
    realtimeStreamChannelForUser("user-1", {
      taskId: "00000000-0000-4000-8000-000000000001",
    }),
    "task:00000000-0000-4000-8000-000000000001",
  );
  assert.equal(
    realtimeStreamChannelForUser("user-1", {
      deviceId: "00000000-0000-4000-8000-000000000002",
    }),
    "device:00000000-0000-4000-8000-000000000002",
  );
});

test("realtime stream shapes additive envelope fields for mobile replay safety", () => {
  const envelope = shapeRealtimeEventEnvelope({
    id: 41,
    topic: "task.updated",
    userId: "user-1",
    deviceId: "device-1",
    taskId: "task-1",
    payload: {
      id: "task-1",
      status: "running",
    },
    createdAt: "2030-01-01T00:00:00.000Z",
  });

  assert.equal(envelope.eventId, "41");
  assert.equal(envelope.seq, 41);
  assert.equal(envelope.cursor, "41");
  assert.equal(envelope.aggregateId, "task-1");
  assert.equal(envelope.type, "task.updated");
  assert.deepEqual(envelope.payload, {
    id: "task-1",
    status: "running",
  });
});

test("realtime envelope strips internal metadata before SSE delivery", () => {
  const envelope = shapeRealtimeEventEnvelope({
    id: 42,
    topic: "message.completed",
    userId: "user-1",
    payload: {
      routeDecision: { route: "server_brain", selectedWorkload: "mobile_chat_fast" },
      assistantMessage: {
        metadata: {
          blocks: [{ type: "text", markdown: "Merhaba" }],
          provider: "private-provider",
          toolTrace: { secret: true },
        },
      },
    },
    createdAt: "2030-01-01T00:00:00.000Z",
  });

  const payload = envelope.payload as Record<string, unknown>;
  assert.deepEqual(payload.routeDecision, {
    route: "server_brain",
    selectedWorkload: "mobile_chat_fast",
  });
  const assistantMessage = payload.assistantMessage as Record<string, unknown>;
  const metadata = assistantMessage.metadata as Record<string, unknown>;
  assert.deepEqual(metadata.blocks, [{ type: "text", markdown: "Merhaba" }]);
  assert.equal("provider" in metadata, false);
  assert.equal("toolTrace" in metadata, false);
});

test("realtime stream slots are bounded and released per user", () => {
  const release = acquireRealtimeStreamSlot("user-limit", 1);
  assert.equal(activeRealtimeStreamCountForUser("user-limit"), 1);
  assert.throws(() => acquireRealtimeStreamSlot("user-limit", 1), /Too many realtime streams/i);

  release();
  assert.equal(activeRealtimeStreamCountForUser("user-limit"), 0);

  const releaseAgain = acquireRealtimeStreamSlot("user-limit", 1);
  releaseAgain();
});

test("runtime websocket redelivers stale running tasks after reconnect", () => {
  const connectionId = "new-connection";
  const baseTask = {
    id: "task-1",
    title: "Desktop task",
    targetDeviceId: "desktop-1",
    queuePosition: 0,
    payload: {},
    requestedCapabilities: ["web_research"],
    summary: null,
    error: null,
    approvalRequest: null,
    dispatchAttemptCount: 0,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    lastAckAt: null,
    deliveryAttemptCount: 0,
    lastDispatchAttemptAt: null,
    deliveryState: "queued" as const,
    selectedDesktopOnline: null,
    routeDecision: null,
    capabilityPreflight: {
      ok: true,
      missingCapabilities: [],
      blockedCapabilities: [],
    },
    canAcceptNow: true,
    createdAt: new Date("2030-01-01T00:00:00.000Z"),
    updatedAt: new Date("2030-01-01T00:00:00.000Z"),
  };

  assert.equal(
    shouldDispatchAssignedRuntimeTask(
      {
        ...baseTask,
        status: "running",
        runtimeConnectionId: "old-connection",
      },
      connectionId,
    ),
    true,
  );
  assert.equal(
    shouldDispatchAssignedRuntimeTask(
      {
        ...baseTask,
        status: "running",
        runtimeConnectionId: connectionId,
      },
      connectionId,
    ),
    false,
  );
  assert.equal(
    shouldDispatchAssignedRuntimeTask(
      {
        ...baseTask,
        status: "waiting_approval",
        runtimeConnectionId: "old-connection",
      },
      connectionId,
    ),
    false,
  );
});

test("realtime stream rejects unowned task scopes", async () => {
  class FakeQuery<T> {
    constructor(private readonly result: T) {}
    from() {
      return this;
    }
    where() {
      return this;
    }
    limit() {
      return this;
    }
    then<TResult1 = T, TResult2 = never>(
      resolve?: ((value: T) => TResult1 | PromiseLike<TResult1>) | null,
      reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
    ) {
      return Promise.resolve(this.result).then(resolve, reject);
    }
  }

  const app = Fastify();
  app.decorate("authenticateUser", async (request) => {
    (request as typeof request & { auth: unknown }).auth = {
      kind: "user",
      sub: "user-1",
      sessionId: "session-1",
      email: "user@example.com",
    };
  });
  app.decorate("db", {
    select() {
      return new FakeQuery([]);
    },
  } as never);
  await app.register(errorHandlerPlugin);
  await app.register(realtimeRoutes, { prefix: "/v1/realtime" });

  const response = await app.inject({
    method: "GET",
    url: "/v1/realtime/stream?taskId=00000000-0000-4000-8000-000000000001",
  });

  assert.equal(response.statusCode, 404);
  await app.close();
});

test("shouldDropSlowSseClient drops connections whose write buffer exceeds the limit", () => {
  assert.equal(shouldDropSlowSseClient({ writableLength: 0 }, 1_048_576), false);
  assert.equal(shouldDropSlowSseClient({ writableLength: 512_000 }, 1_048_576), false);
  assert.equal(shouldDropSlowSseClient({ writableLength: 1_048_577 }, 1_048_576), true);
  // writableLength bilinmiyorsa (test mock'ları) asla düşürme
  assert.equal(shouldDropSlowSseClient({}, 1_048_576), false);
});

test("shouldDropSsePendingWrite drops slow writers after 64 pending events", () => {
  const state = createSsePendingWriteState(64);
  for (let index = 0; index < 64; index += 1) {
    assert.equal(shouldDropSsePendingWrite(state, false), false);
  }
  assert.equal(state.pendingEvents, 64);
  assert.equal(shouldDropSsePendingWrite(state, false), true);

  assert.equal(shouldDropSsePendingWrite(state, true), false);
  assert.equal(state.pendingEvents, 0);
});

test("shouldDropSsePendingWrite keeps normal writers open", () => {
  const state = createSsePendingWriteState(64);
  for (let index = 0; index < 1_000; index += 1) {
    assert.equal(shouldDropSsePendingWrite(state, true), false);
  }
  assert.equal(state.pendingEvents, 0);
});
