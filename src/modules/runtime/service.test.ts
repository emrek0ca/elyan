import assert from "node:assert/strict";
import test from "node:test";
import { hashSecret } from "../../lib/auth-crypto.js";
import { registerRuntime } from "./service.js";

function createSelectBuilder(result: unknown) {
  return {
    from() {
      return this;
    },
    where() {
      return this;
    },
    limit: async () => result,
  };
}

test("registerRuntime replaces the active connection and returns a connection-bound runtime token", async () => {
  const closeCalls: Array<{ deviceId: string; code: number; reason: string }> =
    [];
  const updates: Array<{ values: Record<string, unknown> }> = [];
  const inserts: Array<Record<string, unknown>> = [];
  const deviceRow = {
    id: "11111111-1111-4111-8111-111111111111",
    userId: "user-1",
    label: "Elyan",
    type: "desktop",
    isActive: true,
    deviceKeyHash: await hashSecret("derived-device-secret"),
    platform: "macos",
  };
  const selectResults = [
    [deviceRow],
    [
      {
        planCode: "pro",
        status: "active",
        trialEndsAt: null,
      },
    ],
    [
      {
        count: 1,
      },
    ],
  ];

  const app = {
    config: {
      RUNTIME_TOKEN_TTL: "15m",
    },
    jwt: {
      sign(payload: Record<string, unknown>) {
        return `runtime-token:${String(payload.connectionId ?? "")}`;
      },
    },
    db: {
      select() {
        return createSelectBuilder(selectResults.shift() ?? []);
      },
      update() {
        const entry = { values: {} as Record<string, unknown> };
        updates.push(entry);
        return {
          set(values: Record<string, unknown>) {
            entry.values = values;
            return {
              where: async () => [],
            };
          },
        };
      },
      insert() {
        return {
          values(values: Record<string, unknown>) {
            inserts.push(values);
            return {
              returning: async () => [
                { id: "22222222-2222-4222-8222-222222222222" },
              ],
            };
          },
        };
      },
    },
    services: {
      realtimeHub: {
        closeRuntime(deviceId: string, code: number, reason: string) {
          closeCalls.push({ deviceId, code, reason });
        },
      },
    },
  };

  const result = await registerRuntime(app as never, {
    deviceId: deviceRow.id,
    deviceSecret: "derived-device-secret",
    runtimeVersion: "1.0.0",
    capabilities: ["runtime.status", "task.execution"],
    capabilityStates: {
      "local_files.index": {
        available: true,
        ready: false,
        stats: { rootCount: 0, indexedFileCount: 0, lastScanAt: "" },
        errorCode: "no_approved_roots",
      },
    },
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

  assert.deepEqual(closeCalls, [
    {
      deviceId: deviceRow.id,
      code: 4001,
      reason: "runtime_replaced",
    },
  ]);
  assert.equal(result.runtime.deviceId, deviceRow.id);
  assert.equal(
    result.runtime.connectionId,
    "22222222-2222-4222-8222-222222222222",
  );
  assert.deepEqual(result.capabilities, [
    "runtime.status",
    "task.execution",
    "browser.control",
  ]);
  assert.deepEqual(result.capabilityStates, {
    "browser.control": {
      canonicalCapabilityId: "browser.control",
      adapter: "browser.control",
      ready: true,
      dependencyReady: true,
      permissionReady: false,
      aliases: ["browser.control"],
      version: "1.2.3",
      inputContractHash: "hash-browser-v1",
      handshakeContract: "elyan.runtime_capability_handshake.v1",
    },
    "local_files.index": {
      available: true,
      ready: false,
      stats: { rootCount: 0, indexedFileCount: 0, lastScanAt: "" },
      errorCode: "no_approved_roots",
    },
  });
  assert.equal(result.capabilityReadinessSummary.permissionBlocked, 1);
  assert.equal(result.capabilitySummary.total, 3);
  assert.equal(result.capabilitySummary.categories.runtime, 1);
  assert.equal(result.capabilitySummary.categories.task, 1);
  assert.equal(
    result.tokens.accessToken,
    "runtime-token:22222222-2222-4222-8222-222222222222",
  );
  assert.equal(result.realtime.websocketPath, "/v1/realtime/runtime");
  assert.equal(result.realtime.ssePath, "/v1/realtime/stream");
  assert.equal(inserts.length, 1);
  assert.deepEqual(inserts[0].capabilityStates, {
    "browser.control": {
      canonicalCapabilityId: "browser.control",
      adapter: "browser.control",
      ready: true,
      dependencyReady: true,
      permissionReady: false,
      aliases: ["browser.control"],
      version: "1.2.3",
      inputContractHash: "hash-browser-v1",
      handshakeContract: "elyan.runtime_capability_handshake.v1",
    },
    "local_files.index": {
      available: true,
      ready: false,
      stats: { rootCount: 0, indexedFileCount: 0, lastScanAt: "" },
      errorCode: "no_approved_roots",
    },
  });
  assert.equal(updates.length >= 2, true);
});

test("registerRuntime returns pairing_pending until the desktop is paired", async () => {
  const app = {
    config: {
      RUNTIME_TOKEN_TTL: "15m",
    },
    db: {
      select() {
        return createSelectBuilder([
          {
            id: "11111111-1111-4111-8111-111111111111",
            userId: null,
            label: "Elyan",
            type: "desktop",
            isActive: true,
            deviceKeyHash: null,
            platform: "macos",
          },
        ]);
      },
    },
  };

  await assert.rejects(
    () =>
      registerRuntime(app as never, {
        deviceId: "11111111-1111-4111-8111-111111111111",
        deviceSecret: "derived-device-secret",
        capabilities: ["runtime.status"],
      }),
    (error: unknown) => {
      assert.equal(error instanceof Error, true);
      assert.equal(
        (error as { message: string }).message,
        "Desktop runtime has not completed pairing",
      );
      assert.equal((error as { code?: string }).code, "pairing_pending");
      return true;
    },
  );
});
