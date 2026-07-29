import test from "node:test";
import assert from "node:assert/strict";
import type { DesktopWorkOrder } from "./desktop-work-order.js";
import {
  acquireDesktopPlanMaterializationLock,
  buildDesktopPlanCacheFingerprints,
  buildDesktopPlanCacheKey,
  clearDesktopPlanCacheForTests,
  getDesktopPlanCacheTelemetry,
  readDesktopPlanCache,
  recordDesktopPlanCacheAvoidedCost,
  releaseDesktopPlanMaterializationLock,
  storeDesktopPlanCache,
  waitForDesktopPlanCache,
} from "./plan-cache.js";

function order(summary = "Gizli müşteri raporunu Word yap"): DesktopWorkOrder {
  return {
    schema: "elyan.desktop_work_order.v1",
    source: "mobile_chat_dispatch",
    goal: {
      kind: "desktop_cowork",
      summary,
      language: "tr",
      sourceTextHash: "a".repeat(24),
    },
    entities: [{ type: "topic", value: "Gizli müşteri" }],
    constraints: ["docx üret"],
    requiredCapabilities: ["text_analyze", "document_write"],
    localContextNeeded: [],
    expectedOutputs: [{ kind: "artifact", format: "docx", required: true }],
    verificationRules: [
      { id: "artifact", description: "Artifact üretildi.", evidence: "artifact" },
    ],
    execution: {
      mode: "cowork_dispatch",
      approvalPolicy: "capability_policy",
      maxSteps: 16,
    },
    contextPack: {
      sourceReference: "current_prompt",
      outputContract: {
        operation: "create",
        outputKind: "document",
        outputFormat: "docx",
      },
      conversationState: {
        turnKind: "new_task",
        currentGoal: summary,
      },
    },
    planPreview: {
      summary,
      privacyClass: "local_private",
      steps: [],
    },
  };
}

test("desktop plan cache key carries only bounded digests, not raw goal text", () => {
  const key = buildDesktopPlanCacheKey(order(), [
    "document_write",
    "text_analyze",
  ]);

  assert.equal(key.keyHash.length, 32);
  assert.doesNotMatch(key.key, /Gizli müşteri/u);
  assert.doesNotMatch(key.key, /Word yap/u);
});

test("desktop plan cache separates output contracts and allowed capability scopes", () => {
  const docx = order();
  const pdf = order();
  pdf.expectedOutputs = [{ kind: "artifact", format: "pdf", required: true }];
  pdf.contextPack = {
    sourceReference: "current_prompt",
    conversationState: pdf.contextPack?.conversationState,
    outputContract: {
      operation: "export",
      outputKind: "document",
      outputFormat: "pdf",
    },
  };

  assert.notEqual(
    buildDesktopPlanCacheKey(docx, ["document_write"]).keyHash,
    buildDesktopPlanCacheKey(pdf, ["document_write"]).keyHash,
  );
  assert.notEqual(
    buildDesktopPlanCacheKey(docx, ["document_write"]).keyHash,
    buildDesktopPlanCacheKey(docx, ["document_write", "text_analyze"]).keyHash,
  );
});

test("desktop plan cache fingerprints goal deltas and manifest contracts", () => {
  const base = order("Raporu docx yap");
  const revised = order("Raporu pdf yap");
  revised.expectedOutputs = [{ kind: "artifact", format: "pdf", required: true }];
  revised.contextPack = {
    sourceReference: "current_prompt",
    conversationState: {
      turnKind: "correction",
      currentGoal: "Raporu pdf yap",
    },
    outputContract: {
      operation: "export",
      outputKind: "document",
      outputFormat: "pdf",
    },
  };
  const baseFingerprints = buildDesktopPlanCacheFingerprints(base, [
    "document_write",
  ]);
  const revisedFingerprints = buildDesktopPlanCacheFingerprints(revised, [
    "document_write",
  ]);
  const skillFingerprints = buildDesktopPlanCacheFingerprints(base, [
    "document_write",
    "run_skill",
  ]);

  assert.notEqual(
    baseFingerprints.goalDeltaHash,
    revisedFingerprints.goalDeltaHash,
  );
  assert.equal(baseFingerprints.capabilityManifestHash.length, 32);
  assert.equal(skillFingerprints.capabilityManifestHash.length, 32);
  assert.equal(skillFingerprints.skillManifestHash?.length, 32);
  assert.equal(baseFingerprints.skillManifestHash, undefined);
});

test("desktop plan cache returns cloned validated plan data with scope metadata", async () => {
  clearDesktopPlanCacheForTests();
  const workOrder = order();
  const steps = [
    {
      id: "s1",
      capability: "text_analyze",
      description: "Metni analiz et",
      args: { prompt: "Rapor omurgası çıkar", sourceContext: "context" },
      dependsOn: [],
    },
    {
      id: "s2",
      capability: "document_write",
      description: "Word belgesi üret",
      args: {
        title: "Rapor",
        content: "{{steps.s1.output}}",
        format: "docx",
      },
      dependsOn: ["s1"],
    },
  ];

  const stored = await storeDesktopPlanCache({
    workOrder,
    allowedCapabilities: ["document_write", "text_analyze"],
    steps,
    materializedCapabilityScope: ["text_analyze", "document_write"],
  });
  const hit = await readDesktopPlanCache(workOrder, [
    "document_write",
    "text_analyze",
  ]);

  assert.equal(stored.status, "stored");
  assert.equal(stored.fingerprints.goalDeltaHash.length, 32);
  assert.equal(stored.fingerprints.capabilityManifestHash.length, 32);
  assert.equal(hit?.metadata.status, "hit");
  assert.equal(hit?.metadata.keyHash, stored.keyHash);
  assert.deepEqual(hit?.metadata.fingerprints, stored.fingerprints);
  assert.deepEqual(hit?.materializedCapabilityScope, [
    "text_analyze",
    "document_write",
  ]);
  assert.notEqual(hit?.steps, steps);
  assert.notEqual(hit?.steps[0]?.args, steps[0]?.args);
  hit!.steps[0]!.args.prompt = "mutated";
  const secondHit = await readDesktopPlanCache(workOrder, [
    "document_write",
    "text_analyze",
  ]);
  assert.equal(secondHit?.steps[0]?.args.prompt, "Rapor omurgası çıkar");
  clearDesktopPlanCacheForTests();
});

test("desktop plan cache telemetry records content-free cache impact", async () => {
  clearDesktopPlanCacheForTests();
  const workOrder = order("Gizli maliyet raporunu tekrar planla");
  const steps = [
    {
      id: "s1",
      capability: "text_analyze",
      description: "Raporu analiz et",
      args: { prompt: "Maliyetleri sınıflandır" },
      dependsOn: [],
    },
  ];

  await storeDesktopPlanCache({
    workOrder,
    allowedCapabilities: ["text_analyze"],
    steps,
    materializedCapabilityScope: ["text_analyze"],
  });
  await readDesktopPlanCache(workOrder, ["text_analyze"]);
  recordDesktopPlanCacheAvoidedCost({
    promptBytes: 1_024,
    estimatedTokens: 256,
  });

  const telemetry = getDesktopPlanCacheTelemetry();
  const serialized = JSON.stringify(telemetry);
  assert.equal(telemetry.stores, 1);
  assert.equal(telemetry.reads, 1);
  assert.equal(telemetry.hits, 1);
  assert.equal(telemetry.memoryHits, 1);
  assert.equal(telemetry.estimatedPromptBytesAvoided, 1_024);
  assert.equal(telemetry.estimatedPlanTokensAvoided, 256);
  assert.doesNotMatch(serialized, /Gizli maliyet/u);
  assert.doesNotMatch(serialized, /Maliyetleri/u);
  clearDesktopPlanCacheForTests();
});

test("desktop plan cache uses reliability store without raw key material", async () => {
  clearDesktopPlanCacheForTests();
  const writes: Array<{ key: string; value: string; ttlMs?: number }> = [];
  const values = new Map<string, string>();
  const app = {
    services: {
      reliability: {
        store: {
          async get(key: string) {
            return values.get(key) ?? null;
          },
          async set(key: string, value: string, ttlMs?: number) {
            writes.push({ key, value, ttlMs });
            values.set(key, value);
          },
          async increment(key: string, ttlMs: number) {
            const next = Number(values.get(key) ?? "0") + 1;
            writes.push({ key, value: String(next), ttlMs });
            values.set(key, String(next));
            return next;
          },
        },
      },
    },
  };
  const workOrder = order("Müşteri sözleşmesini analiz et ve rapor hazırla");
  const steps = [
    {
      id: "s1",
      capability: "text_analyze",
      description: "Sözleşme risklerini analiz et",
      args: { prompt: "Riskleri çıkar", sourceContext: "contract digest" },
      dependsOn: [],
    },
  ];

  const stored = await storeDesktopPlanCache({
    app: app as never,
    workOrder,
    allowedCapabilities: ["text_analyze"],
    steps,
    materializedCapabilityScope: ["text_analyze"],
  });
  const hit = await readDesktopPlanCache(
    workOrder,
    ["text_analyze"],
    app as never,
  );

  assert.equal(stored.source, "reliability_store");
  assert.equal(hit?.metadata.source, "reliability_store");
  assert.equal(hit?.metadata.hitCount, 1);
  assert.equal(hit?.metadata.fingerprints.goalDeltaHash.length, 32);
  assert.equal(writes[0]?.key, `tasks:desktop_plan_cache:v1:${stored.keyHash}`);
  assert.doesNotMatch(writes[0]?.key ?? "", /Müşteri|sözleşmesini/u);
  assert.doesNotMatch(writes[0]?.value ?? "", /Müşteri sözleşmesini/u);
  assert.equal(writes[0]?.ttlMs, 15 * 60 * 1000);
  clearDesktopPlanCacheForTests();
});

test("desktop plan cache telemetry records reliability store write failures", async () => {
  clearDesktopPlanCacheForTests();
  const app = {
    services: {
      reliability: {
        store: {
          async get() {
            return null;
          },
          async set() {
            throw new Error("redis unavailable");
          },
        },
      },
    },
  };

  await storeDesktopPlanCache({
    app: app as never,
    workOrder: order("Redis yokken yerel cache'e düş"),
    allowedCapabilities: ["text_analyze"],
    steps: [
      {
        id: "s1",
        capability: "text_analyze",
        description: "İsteği analiz et",
        args: { prompt: "Analiz" },
        dependsOn: [],
      },
    ],
    materializedCapabilityScope: ["text_analyze"],
  });

  const telemetry = getDesktopPlanCacheTelemetry();
  assert.equal(telemetry.stores, 1);
  assert.equal(telemetry.reliabilityStoreWriteAttempts, 1);
  assert.equal(telemetry.reliabilityStoreWriteFailures, 1);
  clearDesktopPlanCacheForTests();
});

test("desktop plan materialization lock prevents duplicate planners and waiters reuse shared cache", async () => {
  clearDesktopPlanCacheForTests();
  const values = new Map<string, string>();
  const locks = new Map<string, string>();
  const lockKeys: string[] = [];
  const app = {
    services: {
      reliability: {
        store: {
          async get(key: string) {
            return values.get(key) ?? null;
          },
          async set(key: string, value: string) {
            values.set(key, value);
          },
          async increment(key: string) {
            const next = Number(values.get(key) ?? "0") + 1;
            values.set(key, String(next));
            return next;
          },
          async acquireLock(key: string, owner: string) {
            lockKeys.push(key);
            if (locks.has(key)) return false;
            locks.set(key, owner);
            return true;
          },
          async releaseLock(key: string, owner: string) {
            if (locks.get(key) !== owner) return false;
            locks.delete(key);
            return true;
          },
        },
      },
    },
  };
  const workOrder = order("Aynı raporu tekrar hazırla");
  const allowed = ["text_analyze"];
  const first = await acquireDesktopPlanMaterializationLock(
    workOrder,
    allowed,
    app as never,
  );
  const second = await acquireDesktopPlanMaterializationLock(
    workOrder,
    allowed,
    app as never,
  );

  assert.equal(first.acquired, true);
  assert.equal(second.acquired, false);
  assert.equal(lockKeys[0], `tasks:desktop_plan_cache:v1:${first.keyHash}:lock`);
  assert.doesNotMatch(lockKeys[0] ?? "", /Aynı raporu/u);

  const waiter = waitForDesktopPlanCache({
    workOrder,
    allowedCapabilities: allowed,
    app: app as never,
    timeoutMs: 1_000,
  });
  await storeDesktopPlanCache({
    app: app as never,
    workOrder,
    allowedCapabilities: allowed,
    steps: [
      {
        id: "s1",
        capability: "text_analyze",
        description: "Raporu analiz et",
        args: { prompt: "Özet çıkar" },
        dependsOn: [],
      },
    ],
    materializedCapabilityScope: ["text_analyze"],
  });
  const hit = await waiter;

  assert.equal(hit?.metadata.status, "hit");
  assert.equal(hit?.metadata.source, "reliability_store");
  assert.equal(hit?.steps[0]?.capability, "text_analyze");
  const afterWait = getDesktopPlanCacheTelemetry();
  assert.equal(afterWait.locksAcquired, 1);
  assert.equal(afterWait.locksContended, 1);
  assert.equal(afterWait.waitHits, 1);

  await releaseDesktopPlanMaterializationLock({
    workOrder,
    allowedCapabilities: allowed,
    owner: first.owner,
    app: app as never,
  });
  const third = await acquireDesktopPlanMaterializationLock(
    workOrder,
    allowed,
    app as never,
  );
  assert.equal(third.acquired, true);
  await releaseDesktopPlanMaterializationLock({
    workOrder,
    allowedCapabilities: allowed,
    owner: third.owner,
    app: app as never,
  });
  clearDesktopPlanCacheForTests();
});
