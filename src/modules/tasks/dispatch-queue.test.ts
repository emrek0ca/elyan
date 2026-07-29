import test from "node:test";
import assert from "node:assert/strict";
import { dispatchClaimedTask } from "./dispatch-queue.js";

test("desktop dispatch materializes and publishes the plan before lease and send", async () => {
  const order: string[] = [];
  const task = {
    id: "task-planned-dispatch",
    userId: "user-1",
    targetDeviceId: "desktop-1",
    runtimeConnectionId: "runtime-1",
    status: "queued",
    payload: {
      metadata: {
        chat: {
          sessionId: "session-1",
          assistantMessageId: "assistant-1",
        },
      },
      desktopWorkOrder: {
        planPreview: {
          planSource: "initial",
          steps: [],
        },
      },
    },
  };
  const app = {
    log: {
      warn() {},
    },
    services: {
      realtimeHub: {
        sendToRuntime() {
          throw new Error("default sender must not be used");
        },
      },
    },
  };

  const dispatched = await dispatchClaimedTask(
    app as never,
    task as never,
    {
      async materialize(_app, candidate) {
        order.push("materialize");
        const payload = candidate.payload as typeof task.payload;
        payload.desktopWorkOrder.planPreview = {
          planSource: "server_materialized",
          steps: [
            {
              id: "s1",
              capability: "directory_tree",
              args: { path: "~/Desktop" },
            },
          ],
        } as never;
        return true;
      },
      async markPrepared(_app, candidate, materialized) {
        order.push("prepare");
        assert.equal(materialized, true);
        const payload = candidate.payload as typeof task.payload;
        (payload.desktopWorkOrder.planPreview as Record<string, unknown>)[
          "planPreparation"
        ] = { status: "ready", outcome: "materialized" };
      },
      async failPlanning() {
        throw new Error("validated plans must not enter the failure path");
      },
      async syncLifecycle(_app, input) {
        order.push("sync");
        const payload = input.updatedTask.payload as typeof task.payload;
        assert.equal(
          payload.desktopWorkOrder.planPreview.planSource,
          "server_materialized",
        );
      },
      async issueLease(_app, input) {
        order.push("lease");
        assert.equal(input.taskId, task.id);
        assert.equal(
          task.payload.desktopWorkOrder.planPreview.planSource,
          "server_materialized",
        );
        return {
          task: task as never,
          lease: {
            leaseId: "lease-1",
            issuedAt: "2030-01-01T00:00:00.000Z",
            expiresAt: "2030-01-01T00:00:45.000Z",
            ackAt: null,
            attemptCount: 1,
            runtimeConnectionId: "runtime-1",
          },
          reused: false,
        };
      },
      async releaseLease() {
        throw new Error("a delivered lease must not be released");
      },
      sendToRuntime(deviceId, envelope) {
        order.push("send");
        const dispatchEnvelope = envelope as {
          type: string;
          task: typeof task;
          leaseId: string;
        };
        assert.equal(deviceId, "desktop-1");
        assert.equal(dispatchEnvelope.type, "task.dispatch");
        assert.equal(dispatchEnvelope.task, task);
        assert.equal(dispatchEnvelope.leaseId, "lease-1");
        const payload = dispatchEnvelope.task.payload;
        assert.equal(
          payload.desktopWorkOrder.planPreview.planSource,
          "server_materialized",
        );
        return true;
      },
    },
  );

  assert.equal(dispatched, "dispatched");
  assert.deepEqual(order, ["materialize", "prepare", "sync", "lease", "send"]);
});

test("desktop dispatch fails closed before lease when model planning is unavailable", async () => {
  const order: string[] = [];
  const task = {
    id: "task-fallback-dispatch",
    targetDeviceId: "desktop-1",
    runtimeConnectionId: null,
    payload: {},
  };

  const dispatched = await dispatchClaimedTask(
    {
      log: { warn() {} },
      services: { realtimeHub: { sendToRuntime() { return true; } } },
    } as never,
    task as never,
    {
      async materialize() {
        order.push("materialize");
        return false;
      },
      async markPrepared(_app, _candidate, materialized) {
        order.push("prepare");
        assert.equal(materialized, false);
      },
      async failPlanning(_app, input) {
        order.push("fail");
        assert.equal(input.task, task);
        return task as never;
      },
      async syncLifecycle() {
        order.push("sync");
      },
      async issueLease() {
        order.push("lease");
        return {
          task: task as never,
          lease: {
            leaseId: "lease-2",
            issuedAt: "2030-01-01T00:00:00.000Z",
            expiresAt: "2030-01-01T00:00:45.000Z",
            ackAt: null,
            attemptCount: 1,
            runtimeConnectionId: null,
          },
          reused: false,
        };
      },
      async releaseLease() {
        order.push("release");
        return true;
      },
      sendToRuntime() {
        order.push("send");
        return true;
      },
    },
  );

  assert.equal(dispatched, "planning_failed");
  assert.deepEqual(order, ["materialize", "prepare", "fail"]);
});

test("desktop dispatch releases an unaccepted lease when runtime send fails", async () => {
  const order: string[] = [];
  const task = {
    id: "task-send-failed",
    targetDeviceId: "desktop-1",
    runtimeConnectionId: "runtime-1",
    payload: {},
  };
  const outcome = await dispatchClaimedTask(
    {
      log: { warn() {} },
      services: { realtimeHub: { sendToRuntime() { return false; } } },
    } as never,
    task as never,
    {
      async materialize() { return true; },
      async markPrepared() {},
      async failPlanning() { throw new Error("unexpected planning failure"); },
      async syncLifecycle() {},
      async issueLease() {
        return {
          task: task as never,
          lease: {
            leaseId: "lease-send-failed",
            issuedAt: "2030-01-01T00:00:00.000Z",
            expiresAt: "2030-01-01T00:00:45.000Z",
            ackAt: null,
            attemptCount: 1,
            runtimeConnectionId: "runtime-1",
          },
          reused: false,
        };
      },
      async releaseLease(_app, input) {
        order.push(`release:${input.taskId}:${input.leaseId}`);
        return true;
      },
      sendToRuntime() {
        order.push("send");
        return false;
      },
    },
  );
  assert.equal(outcome, "not_dispatched");
  assert.deepEqual(order, [
    "send",
    "release:task-send-failed:lease-send-failed",
  ]);
});

test("desktop dispatch resends a queued unacknowledged lease on retry", async () => {
  const sentLeaseIds: string[] = [];
  const task = {
    id: "task-reused-lease",
    targetDeviceId: "desktop-1",
    runtimeConnectionId: "runtime-1",
    payload: {},
  };

  const outcome = await dispatchClaimedTask(
    {
      log: { warn() {} },
      services: { realtimeHub: { sendToRuntime() { return false; } } },
    } as never,
    task as never,
    {
      async materialize() { return true; },
      async markPrepared() {},
      async failPlanning() { throw new Error("unexpected planning failure"); },
      async syncLifecycle() {},
      async issueLease() {
        return {
          task: task as never,
          lease: {
            leaseId: "lease-reused",
            issuedAt: "2030-01-01T00:00:00.000Z",
            expiresAt: "2030-01-01T00:00:45.000Z",
            ackAt: null,
            attemptCount: 1,
            runtimeConnectionId: "runtime-1",
          },
          reused: true,
        };
      },
      async releaseLease() {
        throw new Error("a redelivered lease must not be released");
      },
      sendToRuntime(_deviceId, envelope) {
        sentLeaseIds.push((envelope as { leaseId: string }).leaseId);
        return true;
      },
    },
  );

  assert.equal(outcome, "dispatched");
  assert.deepEqual(sentLeaseIds, ["lease-reused"]);
});
