import assert from "node:assert/strict";
import test from "node:test";
import { getBillingDependencyStatus, getReadiness, summarizeRuntimeOperationalRows } from "./service.js";

function withBrainConfig(config: Record<string, unknown>) {
  return {
    ...config,
    ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
    ELYAN_SHARED_BRAIN_BASE_URL: "https://brain.example.com",
    ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
  };
}

test("getBillingDependencyStatus is ready when store verification env is complete", () => {
  const result = getBillingDependencyStatus({
    APPLE_APP_STORE_ISSUER_ID: "issuer",
    APPLE_APP_STORE_KEY_ID: "key",
    APPLE_APP_STORE_PRIVATE_KEY: "private",
    APPLE_APP_BUNDLE_ID: "com.elyan.app",
    APPLE_APP_ID: 6779045459,
    APPLE_SOLO_PRODUCT_ID: "com.elyan.elyanMobile.solo.monthly",
    APPLE_PRO_PRODUCT_ID: "com.elyan.elyanMobile.pro.monthly",
    GOOGLE_PLAY_PACKAGE_NAME: "",
    GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL: "",
    GOOGLE_PLAY_PRIVATE_KEY: "",
    IYZICO_API_KEY: "",
    IYZICO_SECRET_KEY: "",
    IYZICO_MERCHANT_ID: "",
  });

  assert.equal(result.status, "ready");
  assert.equal(result.checkoutEnabled, true);
  assert.equal(result.storeVerificationEnabled, true);
  assert.equal(result.legacyCheckoutEnabled, false);
  assert.equal(result.provider, "store_first");
  assert.deepEqual(result.availableProviders, ["apple_store"]);
});

test("getBillingDependencyStatus is degraded when no billing provider env is complete", () => {
  const result = getBillingDependencyStatus({
    IYZICO_API_KEY: "api",
    IYZICO_SECRET_KEY: "",
    IYZICO_MERCHANT_ID: undefined,
    APPLE_APP_STORE_ISSUER_ID: "",
    APPLE_APP_STORE_KEY_ID: "",
    APPLE_APP_STORE_PRIVATE_KEY: "",
    APPLE_APP_BUNDLE_ID: "",
    GOOGLE_PLAY_PACKAGE_NAME: "",
    GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL: "",
    GOOGLE_PLAY_PRIVATE_KEY: "",
  });

  assert.equal(result.status, "degraded");
  assert.equal(result.checkoutEnabled, false);
  assert.equal(result.storeVerificationEnabled, false);
  assert.equal(result.legacyCheckoutEnabled, false);
  assert.equal(result.provider, "iyzico");
  assert.deepEqual(result.missingEnv, [
    "APPLE_APP_STORE_ISSUER_ID",
    "APPLE_APP_STORE_KEY_ID",
    "APPLE_APP_STORE_PRIVATE_KEY_OR_PATH",
    "APPLE_APP_BUNDLE_ID",
    "APPLE_APP_ID",
    "APPLE_SOLO_PRODUCT_ID",
    "APPLE_PRO_PRODUCT_ID",
    "GOOGLE_PLAY_PACKAGE_NAME",
    "GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL",
    "GOOGLE_PLAY_PRIVATE_KEY",
    "IYZICO_SECRET_KEY",
    "IYZICO_MERCHANT_ID",
  ]);
});

test("getReadiness exposes mobile-safe diagnostics for external clients", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;
  const readiness = await getReadiness({
    config: withBrainConfig({
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      DATABASE_URL: "postgres://user:pass@db:5432/elyan",
      APPLE_APP_STORE_ISSUER_ID: "issuer",
      APPLE_APP_STORE_KEY_ID: "key",
      APPLE_APP_STORE_PRIVATE_KEY: "private",
      APPLE_APP_BUNDLE_ID: "com.elyan.app",
    }),
    db: {
      execute: async () => [{ ok: 1 }],
    },
  } as never);
  globalThis.fetch = originalFetch;

  assert.equal(readiness.ok, true);
  assert.equal(readiness.agent.chatReady, true);
  assert.equal(readiness.agent.serverBrainReady, true);
  assert.equal(readiness.agent.runtimeDispatchReady, true);
  assert.equal(readiness.agent.desktopTaskReady, false);
  assert.equal(readiness.agent.quantumReady, false);
  assert.equal(readiness.agent.quantumDesktopReady, false);
  assert.equal(readiness.agent.quantumCapabilitiesReady, false);
  assert.deepEqual(readiness.agent.quantumSupportedProblemClasses, []);
  assert.deepEqual(readiness.agent.quantumBlockingReasons, ["desktop_runtime_unavailable", "quantum_capabilities_unavailable"]);
  assert.equal(readiness.agent.neuralReady, false);
  assert.equal(readiness.agent.trainingWorkerReady, false);
  assert.equal(readiness.agent.embeddingReady, false);
  assert.equal(readiness.agent.evaluationReady, false);
  assert.equal(readiness.agent.quantumLearningReady, false);
  assert.equal(readiness.agent.activeTrainingJobs, 0);
  assert.equal(readiness.agent.latestEvaluationScore, null);
  assert.equal(readiness.agent.latestQuantumBenchmarkScore, null);
  assert.equal(readiness.agent.lastChatLatencyMs, null);
  assert.equal(readiness.agent.lastStreamingFirstDeltaMs, null);
  assert.equal(readiness.agent.recentBrainTimeoutCount, 0);
  assert.equal(readiness.agent.mlWorkerMode, null);
  assert.equal(readiness.agent.mlWorkerLastJobAt, null);
  assert.equal(readiness.agent.mlWorkerLastErrorCode, null);
  assert.deepEqual(readiness.agent.optionalLibraries, {});
  assert.equal(readiness.agent.runnerBacklog, null);
  assert.deepEqual(readiness.agent.brainBlockingReasons, ["neural_readiness_unavailable"]);
  assert.equal(readiness.agent.desktopReadyCount, 0);
  assert.equal(readiness.agent.activeRuntimeConnections, 0);
  assert.equal(readiness.agent.staleRuntimeConnections, 0);
  assert.equal(readiness.agent.staleBlockingTaskCount, 0);
  assert.equal(readiness.agent.staleApprovalTaskCount, 0);
  assert.deepEqual(readiness.agent.blockingReasons, []);
  assert.equal(readiness.mobile.statusSummary, "ready");
  assert.equal(readiness.mobile.safeForExternalClients, true);
  assert.deepEqual(readiness.coreSurfaces, [
    "ai",
    "auth",
    "billing",
    "brain",
    "chat",
    "devices",
    "mobile",
    "pairing",
    "realtime",
    "runtime",
    "tasks",
  ]);
  assert.equal(readiness.realtime.sseEnabled, true);
  assert.equal(readiness.realtime.websocketEnabled, true);
  assert.equal(readiness.realtime.heartbeatSeconds, 15);
});

test("getReadiness keeps commercial billing degradation separate from core agent readiness", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;
  const readiness = await getReadiness({
    config: withBrainConfig({
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      DATABASE_URL: "postgres://user:pass@db:5432/elyan",
      APPLE_APP_STORE_ISSUER_ID: "",
      APPLE_APP_STORE_KEY_ID: "",
      APPLE_APP_STORE_PRIVATE_KEY: "",
      APPLE_APP_BUNDLE_ID: "",
      GOOGLE_PLAY_PACKAGE_NAME: "",
      GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL: "",
      GOOGLE_PLAY_PRIVATE_KEY: "",
      IYZICO_API_KEY: "",
      IYZICO_SECRET_KEY: "",
      IYZICO_MERCHANT_ID: "",
    }),
    db: {
      execute: async () => [{ ok: 1 }],
    },
  } as never);
  globalThis.fetch = originalFetch;

  assert.equal(readiness.ok, true);
  assert.equal(readiness.agent.chatReady, true);
  assert.equal(readiness.commercialReadiness.billing.status, "degraded");
  assert.equal(readiness.dependencies.billing.status, "degraded");
});

test("summarizeRuntimeOperationalRows counts only fresh connections as active", () => {
  const now = Date.parse("2030-01-01T00:00:00.000Z");
  const fresh = new Date(now - 30_000);
  const stale = new Date(now - 5 * 60_000);

  const result = summarizeRuntimeOperationalRows(
    [
      {
        status: "online",
        deviceType: "desktop",
        deviceIsActive: true,
        deviceUserId: "user-1",
        lastHeartbeatAt: fresh,
      },
      {
        status: "online",
        deviceType: "desktop",
        deviceIsActive: true,
        deviceUserId: "user-2",
        lastHeartbeatAt: stale,
      },
      {
        status: "offline",
        deviceType: "desktop",
        deviceIsActive: true,
        deviceUserId: "user-3",
        lastHeartbeatAt: stale,
      },
    ],
    now,
  );

  assert.equal(result.activeRuntimeConnections, 1);
  assert.equal(result.staleRuntimeConnections, 1);
  assert.equal(result.desktopReadyCount, 1);
  assert.equal(result.desktopTaskReady, true);
  assert.equal(result.quantumReady, false);
  assert.deepEqual(result.quantumBlockingReasons, ["quantum_capabilities_unavailable"]);
  assert.equal(result.latestDesktopHeartbeatAgeSeconds, 30);
});

test("summarizeRuntimeOperationalRows reports quantum readiness only for fresh capable desktops", () => {
  const now = Date.parse("2030-01-01T00:00:00.000Z");
  const fresh = new Date(now - 15_000);

  const result = summarizeRuntimeOperationalRows(
    [
      {
        status: "online",
        deviceType: "desktop",
        deviceIsActive: true,
        deviceUserId: "user-1",
        lastHeartbeatAt: fresh,
        capabilities: [
          "runtime.status",
          "quantum.model.problem",
          "quantum.run.experiment",
          "quantum.compare.classical",
          "quantum.generate.report",
        ],
      },
    ],
    now,
  );

  assert.equal(result.desktopTaskReady, true);
  assert.equal(result.quantumReady, true);
  assert.equal(result.quantumDesktopReady, true);
  assert.equal(result.quantumCapabilitiesReady, true);
  assert.deepEqual(result.quantumSupportedProblemClasses, ["qubo", "ising", "qaoa", "vqe"]);
  assert.deepEqual(result.quantumBlockingReasons, []);
});

test("summarizeRuntimeOperationalRows keeps quantum readiness false without execution capability", () => {
  const now = Date.parse("2030-01-01T00:00:00.000Z");
  const fresh = new Date(now - 15_000);

  const result = summarizeRuntimeOperationalRows(
    [
      {
        status: "online",
        deviceType: "desktop",
        deviceIsActive: true,
        deviceUserId: "user-1",
        lastHeartbeatAt: fresh,
        capabilities: [
          "runtime.status",
          "quantum.model.problem",
          "quantum.compare.classical",
          "quantum.generate.report",
        ],
      },
    ],
    now,
  );

  assert.equal(result.desktopTaskReady, true);
  assert.equal(result.quantumReady, false);
  assert.equal(result.quantumDesktopReady, false);
  assert.equal(result.quantumCapabilitiesReady, false);
  assert.deepEqual(result.quantumBlockingReasons, ["quantum_capabilities_unavailable"]);
});

test("summarizeRuntimeOperationalRows reports no desktop task readiness without fresh desktop heartbeat", () => {
  const now = Date.parse("2030-01-01T00:00:00.000Z");
  const stale = new Date(now - 5 * 60_000);

  const result = summarizeRuntimeOperationalRows(
    [
      {
        status: "busy",
        deviceType: "desktop",
        deviceIsActive: true,
        deviceUserId: "user-1",
        lastHeartbeatAt: stale,
      },
    ],
    now,
  );

  assert.equal(result.activeRuntimeConnections, 0);
  assert.equal(result.staleRuntimeConnections, 1);
  assert.equal(result.desktopReadyCount, 0);
  assert.equal(result.desktopTaskReady, false);
  assert.equal(result.latestDesktopHeartbeatAgeSeconds, 300);
});
