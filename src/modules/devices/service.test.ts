import assert from "node:assert/strict";
import test from "node:test";
import {
  hasLiveRuntimeConnection,
  isUndefinedColumnError,
  mobileRegistrationAuditMetadata,
  shapeUserDevice,
} from "./service.js";
import { registerMobileDeviceBodySchema } from "./schemas.js";

const now = new Date("2026-05-13T00:02:00.000Z").getTime();
const staleTimestamp = new Date(now - 5 * 60_000 - 1);
const freshTimestamp = new Date(now - 30_000);

function createDevice() {
  return {
    id: "device-1",
    type: "desktop",
    externalDeviceId: null,
    label: "User MacBook Pro",
    platform: "macos",
    runtimeVersion: "1.0.0",
    appVersion: null,
    isActive: true,
    pairedAt: freshTimestamp,
    lastSeenAt: freshTimestamp,
    createdAt: freshTimestamp,
    updatedAt: freshTimestamp,
  } as const;
}

function createRuntime(
  status: "online" | "busy" | "idle" | "offline",
  lastHeartbeatAt = freshTimestamp,
) {
  return {
    id: "runtime-1",
    deviceId: "device-1",
    status,
    capabilities: ["filesystem"],
    capabilityStates: {
      "local_files.index": {
        available: true,
        ready: false,
        stats: {
          rootCount: 1,
          indexedFileCount: 0,
          lastScanAt: "2026-06-03T00:00:00Z",
        },
        errorCode: "no_approved_roots",
      },
    },
    currentTaskId: null,
    connectedAt: lastHeartbeatAt,
    lastHeartbeatAt,
  } as const;
}

test("shapeUserDevice keeps registered-but-not-connected runtimes offline", () => {
  const shaped = shapeUserDevice(
    createDevice() as never,
    createRuntime("offline", staleTimestamp) as never,
    true,
    now,
  );

  assert.equal(shaped.isOnline, false);
  assert.equal(shaped.canReceiveTasks, false);
  assert.equal(shaped.targetStatus, "offline");
  assert.equal(shaped.runtime.isConnected, false);
  assert.equal(shaped.runtime.stale, false);
});

test("shapeUserDevice reports stale live runtimes separately from offline devices", () => {
  const shaped = shapeUserDevice(
    createDevice() as never,
    createRuntime("online", staleTimestamp) as never,
    true,
    now,
  );

  assert.equal(shaped.isOnline, false);
  assert.equal(shaped.canReceiveTasks, false);
  assert.equal(shaped.targetStatus, "runtime_stale");
  assert.equal(shaped.targetErrorCode, "runtime_stale");
  assert.equal(shaped.runtime.isConnected, false);
  assert.equal(shaped.runtime.stale, true);
});

test("shapeUserDevice fails closed when backend advertised base url is not externally reachable", () => {
  const shaped = shapeUserDevice(
    createDevice() as never,
    createRuntime("online") as never,
    false,
    now,
  );

  assert.equal(shaped.isOnline, true);
  assert.equal(shaped.canReceiveTasks, false);
  assert.equal(shaped.targetStatus, "backend_unreachable");
  assert.equal(shaped.targetErrorCode, "backend_unreachable");
});

test("shapeUserDevice reports ready only when runtime is live and backend is reachable", () => {
  const shaped = shapeUserDevice(
    createDevice() as never,
    createRuntime("online") as never,
    true,
    now,
  );

  assert.equal(shaped.isOnline, true);
  assert.equal(shaped.canReceiveTasks, true);
  assert.equal(shaped.targetStatus, "ready");
  assert.equal(shaped.targetErrorCode, null);
  assert.deepEqual(shaped.runtime.capabilityStates, {
    "local_files.index": {
      available: true,
      ready: false,
      stats: {
        rootCount: 1,
        indexedFileCount: 0,
        lastScanAt: "2026-06-03T00:00:00Z",
      },
      errorCode: "no_approved_roots",
    },
  });
});

test("shapeUserDevice marks desktop targets as plan restricted when desktop access is disabled", () => {
  const shaped = shapeUserDevice(
    createDevice() as never,
    createRuntime("online") as never,
    true,
    {
      desktopAllowed: false,
    },
    now,
  );

  assert.equal(shaped.isOnline, true);
  assert.equal(shaped.canReceiveTasks, false);
  assert.equal(shaped.targetStatus, "plan_restricted");
  assert.equal(shaped.targetErrorCode, "desktop_plan_required");
});

test("mobile registration recognizes a missing client metadata migration", () => {
  assert.equal(isUndefinedColumnError({ code: "42703" }), true);
  assert.equal(isUndefinedColumnError({ code: "23505" }), false);
  assert.equal(isUndefinedColumnError(new Error("42703")), false);
});

test("mobile registration audit metadata never includes the push token", () => {
  const metadata = mobileRegistrationAuditMetadata({
    pushToken: "private-apns-token",
    pushProvider: "apns",
    notificationAuthorizationStatus: "authorized",
    supportsLiveActivities: true,
  });

  assert.equal(metadata.pushConfigured, true);
  assert.equal(metadata.pushProvider, "apns");
  assert.equal("pushToken" in metadata, false);
});

test("mobile registration accepts only server-owned capability names", () => {
  const base = {
    externalDeviceId: "installation-1",
    label: "User iPhone",
    platform: "ios",
  };
  const parsed = registerMobileDeviceBodySchema.parse({
    ...base,
    capabilities: ["present_file", "share"],
  });
  assert.deepEqual(parsed.capabilities, ["present_file", "share"]);
  assert.throws(() =>
    registerMobileDeviceBodySchema.parse({
      ...base,
      capabilities: ["shell_run"],
    }),
  );
});

function fakeAppWithConnection(row: unknown) {
  const chain = {
    from: () => chain,
    where: () => chain,
    orderBy: () => chain,
    limit: async () => (row === null ? [] : [row]),
  };
  return { db: { select: () => chain } } as unknown as Parameters<
    typeof hasLiveRuntimeConnection
  >[0];
}

test("eşleştirme canlılığı soketten okunur, lastSeenAt damgasından değil", async () => {
  // CANLI ARIZA (2026-08-13): kullanıcı masaüstünde `unpair` yaptı, `pair` ile
  // yeni kod aldı, mobilde kodu girince "Desktop runtime is already paired with
  // another user" gördü. O anda ölçüm:
  //
  //   devices.last_seen_at = 08:13:49  (taze → çakışma "canlı" sandı)
  //   runtime_connections  = offline, son heartbeat 04:26, disconnected_at dolu
  //
  // Yani hiç bağlantısı olmayan makine "başka kullanıcıya bağlı" sayılıyordu ve
  // kullanıcı kendi bilgisayarını geri alamıyordu.
  assert.equal(
    await hasLiveRuntimeConnection(
      fakeAppWithConnection({
        status: "offline",
        lastHeartbeatAt: new Date(),
        disconnectedAt: null,
      }),
      "device-1",
    ),
    false,
    "offline kayıt canlı sayılmamalı",
  );

  assert.equal(
    await hasLiveRuntimeConnection(
      fakeAppWithConnection({
        status: "online",
        lastHeartbeatAt: new Date(),
        disconnectedAt: new Date(),
      }),
      "device-1",
    ),
    false,
    "kopmuş kayıt canlı sayılmamalı",
  );

  assert.equal(
    await hasLiveRuntimeConnection(
      fakeAppWithConnection({
        status: "online",
        lastHeartbeatAt: new Date(Date.now() - 6 * 60_000),
        disconnectedAt: null,
      }),
      "device-1",
    ),
    false,
    "bayat heartbeat canlı sayılmamalı",
  );

  // KORUMA ZAYIFLAMAZ: başka kullanıcının O AN bağlı masaüstü devralınamaz.
  assert.equal(
    await hasLiveRuntimeConnection(
      fakeAppWithConnection({
        status: "online",
        lastHeartbeatAt: new Date(),
        disconnectedAt: null,
      }),
      "device-1",
    ),
    true,
  );

  assert.equal(await hasLiveRuntimeConnection(fakeAppWithConnection(null), "device-1"), false);
  assert.equal(await hasLiveRuntimeConnection(fakeAppWithConnection(null), ""), false);
});
