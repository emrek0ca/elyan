import assert from "node:assert/strict";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import test from "node:test";
import {
  appendTaskArtifacts,
  buildRuntimeTaskDispatchEnvelope,
  buildRouteDecisionLogEntry,
  createTask,
  isRemoteMcpRouteDecisionStale,
  readServerBrainCompletionMetadata,
  reconcileStaleRuntimeTasks,
  summarizeToolFlowForTrace,
  updateTaskFromRuntime,
} from "./service.js";

test("late remote MCP capability invalidates an earlier server-brain route", () => {
  const staleServerRoute = {
    route: "server_brain",
    mode: "chat",
    capabilities: [],
    privacyClass: "public_text",
    requiresApproval: false,
    reason: "initial_chat_route",
    intent: "normal_chat",
    confidence: 0.8,
    requiredRuntime: "server",
    privacyLevel: "low",
    shouldAskClarification: false,
    failClosedReason: null,
    selectedWorkload: "mobile_chat_fast",
  } as const satisfies Partial<CommandRouteDecision> as CommandRouteDecision;

  assert.equal(
    isRemoteMcpRouteDecisionStale(staleServerRoute, ["mcp_call_tool"]),
    true,
  );
  assert.equal(
    isRemoteMcpRouteDecisionStale(
      { ...staleServerRoute, capabilities: ["mcp_call_tool"] },
      ["mcp_call_tool"],
    ),
    false,
  );
});

test("tool flow trace exposes only the safe connector error code", () => {
  const summary = summarizeToolFlowForTrace([
    {
      tool: "drive.search",
      ok: false,
      permission: "read",
      durationMs: 42,
      errorCode: "connector_auth_required",
      output: null,
    },
  ]);

  assert.deepEqual(summary, {
    count: 1,
    okCount: 0,
    tools: [
      {
        name: "drive.search",
        ok: false,
        resultCount: null,
        errorCode: "connector_auth_required",
      },
    ],
  });
});

test("runtime dispatch envelope preserves the executable desktop work order", () => {
  const task = {
    id: "task-runtime-1",
    payload: {
      prompt: "Masaüstü cowork görevi",
      desktopWorkOrder: {
        schema: "elyan.desktop_work_order.v1",
        entities: [{ type: "topic", value: "TextEdit uygulamasını aç." }],
      },
    },
    requestedCapabilities: ["open_app"],
  } as unknown as Parameters<typeof buildRuntimeTaskDispatchEnvelope>[0];

  const envelope = buildRuntimeTaskDispatchEnvelope(task, {
    leaseId: "lease-runtime-1",
    expiresAt: "2030-01-01T00:00:45.000Z",
  });

  assert.equal(envelope.type, "task.dispatch");
  assert.equal(envelope.leaseId, "lease-runtime-1");
  assert.equal(envelope.task, task);
  const dispatchedPayload = envelope.task.payload as {
    desktopWorkOrder: { entities: Array<{ value: string }> };
  };
  assert.equal(
    dispatchedPayload.desktopWorkOrder.entities[0]?.value,
    "TextEdit uygulamasını aç.",
  );
});

class FakeQuery<T> {
  constructor(private readonly result: T) {}

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  groupBy() {
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

class FakeDb {
  readonly inserted: any[] = [];

  constructor(private readonly selects: unknown[]) {}

  select() {
    return new FakeQuery(this.selects.shift() ?? []);
  }

  insert() {
    return this.createInsertBuilder();
  }

  transaction<T>(callback: (tx: unknown) => Promise<T>) {
    const tx = {
      execute: async () => undefined,
      select: () => new FakeQuery([{ count: 0 }]),
      insert: () => this.createInsertBuilder({ taskInsert: true }),
    };
    return callback(tx);
  }

  private createInsertBuilder(options: { taskInsert?: boolean } = {}) {
    const inserted = this.inserted;
    return {
      values(values: Record<string, unknown> | Record<string, unknown>[]) {
        inserted.push(values);
        return {
          returning: async () => {
            const now = new Date("2030-01-01T00:00:00.000Z");
            const rows = Array.isArray(values) ? values : [values];
            if (!options.taskInsert) {
              return rows.map((row, index) => ({
                id: `inserted-row-${index + 1}`,
                ...row,
              }));
            }
            return [
              {
                id: "task-blocked-1",
                queuePosition: rows[0]?.queuePosition ?? 1,
                status: rows[0]?.status ?? "queued",
                createdAt: rows[0]?.createdAt ?? now,
                updatedAt: rows[0]?.updatedAt ?? now,
                ...rows[0],
              },
            ];
          },
        };
      },
    };
  }
}

class SequenceDb {
  readonly updates: any[] = [];
  readonly inserts: any[] = [];

  constructor(private readonly selects: unknown[]) {}

  select() {
    return new FakeQuery(this.selects.shift() ?? []);
  }

  update() {
    const updates = this.updates;
    return {
      set(values: Record<string, unknown>) {
        updates.push(values);
        return {
          where() {
            return {
              returning: async () => [
                {
                  id: "task-stale-1",
                  userId: "user-1",
                  targetDeviceId: "desktop-1",
                  title: "Desktop task",
                  payload: {},
                  requestedCapabilities: ["web_research"],
                  runtimeConnectionId: values.runtimeConnectionId ?? null,
                  dispatchLeaseId: values.dispatchLeaseId ?? null,
                  dispatchLeaseIssuedAt: values.dispatchLeaseIssuedAt ?? null,
                  dispatchLeaseExpiresAt: values.dispatchLeaseExpiresAt ?? null,
                  dispatchAckAt: values.dispatchAckAt ?? null,
                  status: values.status ?? "failed",
                  queuePosition: values.queuePosition ?? 0,
                  summary: values.summary ?? null,
                  error: values.error ?? null,
                  approvalRequest: null,
                  result: values.result ?? null,
                  createdAt: new Date("2030-01-01T00:00:00.000Z"),
                  startedAt: null,
                  completedAt: values.completedAt ?? null,
                  canceledAt: null,
                  updatedAt: values.updatedAt ?? new Date("2030-01-01T00:00:00.000Z"),
                },
              ],
            };
          },
        };
      },
    };
  }

  insert() {
    const inserts = this.inserts;
    return {
      values(values: Record<string, unknown> | Record<string, unknown>[]) {
        inserts.push(values);
        return {
          returning: async () => {
            const rows = Array.isArray(values) ? values : [values];
            return rows.map((row, index) => ({
              id: `event-${index + 1}`,
              ...row,
            }));
          },
        };
      },
    };
  }
}

class ReadOnlyTaskDb {
  constructor(private readonly selects: unknown[]) {}

  select() {
    return new FakeQuery(this.selects.shift() ?? []);
  }

  update() {
    throw new Error("duplicate terminal runtime update should not write");
  }

  insert() {
    throw new Error("duplicate terminal runtime update should not insert");
  }
}

test("createTask materializes pairing-required chat tasks without dispatching to server brain execution", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const db = new FakeDb([
    [
      {
        planCode: "free",
        status: "trialing",
        trialEndsAt: new Date("2099-01-01T00:00:00.000Z"),
      },
    ],
    [
      {
        planCode: "free",
        status: "trialing",
        trialEndsAt: new Date("2099-01-01T00:00:00.000Z"),
      },
    ],
    [],
    [
      {
        id: "shared-brain-device",
        type: "desktop",
        externalDeviceId: "shared-brain",
        label: "Elyan",
        platform: "server",
        runtimeVersion: "server",
        appVersion: null,
        isActive: true,
        pairedAt: now,
        lastSeenAt: now,
        createdAt: now,
        updatedAt: now,
      },
    ],
    [],
  ]);
  const published: Array<Record<string, unknown>> = [];
  const app = {
    db,
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      ELYAN_USER_UNDERSTANDING_ENABLED: false,
      ELYAN_PERSONALIZATION_ENABLED: false,
      ELYAN_LEARNING_EXTRACTION_ENABLED: false,
    },
    log: {
      info() {},
      warn() {},
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
      realtimeHub: {
        sendToRuntime() {
          throw new Error("blocked route must not dispatch to runtime");
        },
      },
    },
  };

  const result = await createTask(app as never, {
    userId: "user-1",
    title: "Atatürk hakkında araştırma yap ve ali@example.com adresine mail gönder.",
    payload: {
      prompt: "Atatürk hakkında araştırma yap ve ali@example.com adresine mail gönder.",
      source: "mobile",
      metadata: {
        routeDecision: {
          route: "pairing_required",
          mode: "mixed_task",
          capabilities: ["web_research", "email_draft", "email_send"],
          privacyClass: "side_effect",
          requiresApproval: true,
          reason: "Yerel runtime gerekli ama bağlı ve yetenekli bir masaüstü bulunamadı.",
          userFacingMessage: "Bu görev için önce bir masaüstü eşleştirmen gerekiyor.",
        },
      },
    },
    requestedCapabilities: [],
    requestId: "req-1",
  });

  assert.equal(result.dispatched, false);
  assert.equal(result.reused, false);
  assert.equal(result.task.status, "queued");
  assert.equal(result.task.targetDeviceId, "shared-brain-device");
  assert.equal(result.task.summary, "Bu görev için önce bir masaüstü eşleştirmen gerekiyor.");
  assert.equal(result.task.error, null);
  assert.equal(published.length, 0);
  assert.equal(
    db.inserted.some((item) => item.status === "queued" && item.summary === "Bu görev için önce bir masaüstü eşleştirmen gerekiyor."),
    true,
  );
});

test("buildRouteDecisionLogEntry keeps route logging safe and ignores selected desktop on server-brain routes", () => {
  const entry = buildRouteDecisionLogEntry({
    taskId: "task-1",
    origin: "mobile",
    requestedTargetDeviceId: "desktop-1",
    routeDecision: {
      route: "server_brain",
      taskRoute: {
        operationalRoute: "server_brain",
        executionPlan: ["mobile_local", "server_brain"],
        needsDesktop: false,
      },
    } as never,
  });

  assert.deepEqual(entry, {
    taskId: "task-1",
    origin: "mobile",
    operationalRoute: "server_brain",
    executionPlan: ["mobile_local", "server_brain"],
    needsDesktop: false,
    selectedDeviceIgnored: true,
  });
});

test("readServerBrainCompletionMetadata preserves web grounding metadata for all completion paths", () => {
  const metadata = readServerBrainCompletionMetadata({
    groundingUsed: true,
    documentSourceCount: 6,
    webGroundingUsed: true,
    webSourceCount: 4,
    responseBudgetReason: "long_form_expanded",
    contextPacketCount: 5,
    contextPacketKinds: ["health_context", "calendar_context", "device_context"],
    healthContextUsed: true,
    freshData: {
      schemaVersion: "elyan.fresh_data.v1",
      domain: "market",
      status: "fresh",
      freshnessRequired: true,
      requestedAt: "2026-07-09T12:00:00.000Z",
      retrievedAt: "2026-07-09T12:00:00.000Z",
      freshUntil: "2026-07-09T12:00:30.000Z",
      staleUntil: "2026-07-09T12:02:30.000Z",
      ageMs: 0,
      cache: { state: "miss", shared: false },
      evidence: {
        sourceCount: 2,
        freshSourceCount: 2,
        verifiedSourceCount: 2,
        freshVerifiedSourceCount: 2,
        datedSourceCount: 0,
        freshDatedSourceCount: 0,
        independentHostCount: 2,
        minimumSources: 2,
        minimumVerifiedSources: 2,
        minimumDatedSources: 0,
        numericCorroborated: true,
        sufficient: true,
      },
      reasons: ["fresh"],
      extraInternalField: "drop-me",
    },
    blocks: [{ type: "context_signal", title: "Web kaynakları" }],
  });

  assert.equal(metadata.groundingUsed, true);
  assert.equal(metadata.documentSourceCount, 6);
  assert.equal(metadata.webGroundingUsed, true);
  assert.equal(metadata.webSourceCount, 4);
  assert.equal(metadata.responseBudgetReason, "long_form_expanded");
  assert.equal(metadata.contextPacketCount, 5);
  assert.equal(metadata.freshDataDomain, "market");
  assert.equal(metadata.freshDataStatus, "fresh");
  assert.equal(metadata.freshDataEvidenceSufficient, true);
  assert.ok(metadata.freshData);
  assert.equal((metadata.freshData as Record<string, unknown>).extraInternalField, undefined);
  assert.deepEqual(metadata.contextPacketKinds, [
    "health_context",
    "calendar_context",
    "device_context",
  ]);
  assert.equal(metadata.healthContextUsed, true);
  assert.deepEqual(metadata.assistantBlocks, [{ type: "context_signal", title: "Web kaynakları" }]);
});

test("readServerBrainCompletionMetadata rejects invalid fresh-data scalar metadata", () => {
  const metadata = readServerBrainCompletionMetadata({
    freshDataDomain: "not-a-domain",
    freshDataStatus: "not-a-status",
    freshDataEvidenceSufficient: true,
  });

  assert.equal(metadata.freshData, null);
  assert.equal(metadata.freshDataDomain, null);
  assert.equal(metadata.freshDataStatus, null);
  assert.equal(metadata.freshDataEvidenceSufficient, true);
});

test("reconcileStaleRuntimeTasks returns old active desktop tasks to the queue when runtime is unavailable", async () => {
  const now = new Date("2030-01-01T00:05:00.000Z");
  const oldDate = new Date("2030-01-01T00:00:00.000Z");
  const db = new SequenceDb([
    [
      {
        id: "task-stale-1",
        userId: "user-1",
        targetDeviceId: "desktop-1",
        title: "Desktop task",
        payload: {},
        requestedCapabilities: ["web_research"],
        status: "running",
        queuePosition: 1,
        summary: null,
        error: null,
        approvalRequest: null,
        result: null,
        createdAt: oldDate,
        startedAt: oldDate,
        completedAt: null,
        canceledAt: null,
        updatedAt: oldDate,
      },
    ],
    [
      {
        id: "desktop-1",
        type: "desktop",
        externalDeviceId: "elyan-desktop",
        label: "Elyan Desktop",
        platform: "macos",
        runtimeVersion: "1.0.0",
        appVersion: null,
        isActive: true,
        pairedAt: oldDate,
        lastSeenAt: oldDate,
        createdAt: oldDate,
        updatedAt: oldDate,
      },
    ],
    [],
    [],
  ]);
  const published: Array<Record<string, unknown>> = [];
  const app = {
    db,
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
    },
  };

  const result = await reconcileStaleRuntimeTasks(app as never, {
    userId: "user-1",
    now,
  });

  assert.equal(result.reconciled.length, 1);
  assert.equal(result.reconciled[0]?.status, "queued");
  assert.equal(result.reconciled[0]?.error ?? null, null);
  assert.equal(db.updates[0]?.status, "queued");
  assert.equal(db.inserts[0]?.status, "queued");
  assert.equal((db.inserts[0]?.payload as { reason?: string }).reason, "runtime_execution_stale");
  assert.equal(published[0]?.topic, "command.queued");
});

test("reconcileStaleRuntimeTasks fails stale server-brain chat tasks instead of requeueing forever", async () => {
  const now = new Date("2030-01-01T00:05:00.000Z");
  const oldDate = new Date("2030-01-01T00:00:00.000Z");
  const db = new SequenceDb([
    [
      {
        id: "task-stale-1",
        userId: "user-1",
        targetDeviceId: "server-brain",
        title: "Chat task",
        payload: {
          prompt: "Selam",
          metadata: {
            channel: "chat",
            presentation: "chat",
            chat: {
              sessionId: "session-1",
              assistantMessageId: "message-1",
            },
            routeDecision: {
              route: "server_brain",
            },
          },
        },
        requestedCapabilities: [],
        runtimeConnectionId: null,
        status: "running",
        queuePosition: 1,
        summary: null,
        error: null,
        approvalRequest: null,
        result: null,
        createdAt: oldDate,
        startedAt: oldDate,
        completedAt: null,
        canceledAt: null,
        updatedAt: oldDate,
      },
    ],
    [],
  ]);
  const published: Array<Record<string, unknown>> = [];
  const app = {
    db,
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
    },
  };

  const result = await reconcileStaleRuntimeTasks(app as never, {
    userId: "user-1",
    now,
  });

  assert.equal(result.reconciled.length, 1);
  assert.equal(result.reconciled[0]?.status, "failed");
  assert.equal(db.updates[0]?.status, "failed");
  assert.equal(db.inserts[0]?.status, "failed");
  assert.equal((db.inserts[0]?.payload as { reason?: string }).reason, "server_brain_chat_stale");
  assert.equal(published[0]?.topic, "task.updated");
});

test("updateTaskFromRuntime ignores duplicate terminal updates from the same runtime", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const task = {
    id: "3f4f4d34-4d5d-4696-8f67-5c18bc1f7e21",
    userId: "user-1",
    targetDeviceId: "desktop-1",
    title: "Desktop task",
    payload: {},
    requestedCapabilities: [],
    status: "completed",
    queuePosition: 1,
    summary: "Hazır",
    error: null,
    approvalRequest: null,
    result: { ok: true },
    runtimeConnectionId: "runtime-1",
    createdAt: now,
    startedAt: now,
    completedAt: now,
    canceledAt: null,
    updatedAt: now,
  };
  const app = {
    db: new ReadOnlyTaskDb([
      [task],
      [
        {
          id: "runtime-1",
          deviceId: "desktop-1",
          userId: "user-1",
          status: "online",
          connectedAt: now,
          lastHeartbeatAt: now,
          disconnectedAt: null,
        },
      ],
    ]),
  };

  const result = await updateTaskFromRuntime(app as never, {
    kind: "runtime",
    sub: "user-1",
    deviceId: "desktop-1",
    deviceType: "desktop",
    connectionId: "runtime-1",
  }, task.id, {
    status: "completed",
    message: "Görev tamamlandı.",
    summary: "Hazır",
    result: { ok: true },
    artifacts: [],
  });

  assert.equal(result.replaySkipped, true);
  assert.equal(result.task.status, "completed");
  assert.deepEqual(result.storedArtifacts, []);
});

test("appendTaskArtifacts returns shaped artifact truth for mobile viewers", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const db = new SequenceDb([
    [
      {
        id: "task-1",
        userId: "user-1",
        targetDeviceId: "desktop-1",
        title: "Desktop task",
        payload: {},
        requestedCapabilities: [],
        status: "running",
        queuePosition: 1,
        summary: null,
        error: null,
        approvalRequest: null,
        result: null,
        runtimeConnectionId: "runtime-1",
        createdAt: now,
        startedAt: now,
        completedAt: null,
        canceledAt: null,
        updatedAt: now,
      },
    ],
    [
      {
        id: "runtime-1",
        deviceId: "desktop-1",
        userId: "user-1",
        status: "online",
        connectedAt: now,
        lastHeartbeatAt: now,
        disconnectedAt: null,
      },
    ],
  ]);
  const published: Array<Record<string, unknown>> = [];
  const app = {
    db,
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
    },
  };

  const result = await appendTaskArtifacts(
    app as never,
    {
      kind: "runtime",
      sub: "user-1",
      deviceId: "desktop-1",
      deviceType: "desktop",
      connectionId: "runtime-1",
    },
    "task-1",
    [
      {
        kind: "file",
        name: "Product Brief.pdf",
        contentType: "application/pdf",
        storageKey: "elyan://artifacts/product-brief.pdf",
        textContent: "Bu belge özeti",
        metadata: {
          sourceType: "task_artifact",
        },
      },
    ],
  );

  assert.equal(result.artifacts.length, 1);
  assert.equal(result.artifacts[0]?.viewerHint, "pdf");
  assert.equal(result.artifacts[0]?.contentFamily, "document");
  assert.equal(result.artifacts[0]?.downloadable, true);
  assert.equal(result.artifacts[0]?.previewText, "Bu belge özeti");
  assert.equal(published[0]?.topic, "task.artifacts");
  assert.equal((published[0]?.payload as { artifacts?: Array<{ viewerHint?: string }> }).artifacts?.[0]?.viewerHint, "pdf");
});

test("reconcileStaleRuntimeTasks keeps healthy long-running runtime-owned tasks in place", async () => {
  const now = new Date("2030-01-01T00:05:00.000Z");
  const oldDate = new Date("2030-01-01T00:00:00.000Z");
  const freshHeartbeat = new Date("2030-01-01T00:04:30.000Z");
  const db = new SequenceDb([
    [
      {
        id: "task-running-fresh",
        deviceId: "desktop-1",
        userId: "user-1",
        targetDeviceId: "desktop-1",
        title: "Desktop task",
        payload: {},
        requestedCapabilities: ["web_research"],
        status: "running",
        queuePosition: 1,
        summary: null,
        error: null,
        approvalRequest: null,
        result: null,
        runtimeConnectionId: "runtime-fresh-1",
        createdAt: oldDate,
        startedAt: oldDate,
        completedAt: null,
        canceledAt: null,
        updatedAt: oldDate,
      },
    ],
    [
      {
        planCode: "pro",
        status: "active",
        trialEndsAt: null,
      },
    ],
    [
      {
        id: "desktop-1",
        type: "desktop",
        externalDeviceId: "elyan-desktop",
        label: "Elyan Desktop",
        platform: "macos",
        runtimeVersion: "1.0.0",
        appVersion: null,
        isActive: true,
        pairedAt: oldDate,
        lastSeenAt: freshHeartbeat,
        createdAt: oldDate,
        updatedAt: oldDate,
      },
    ],
    [
      {
        id: "runtime-fresh-1",
        deviceId: "desktop-1",
        status: "online",
        capabilities: [],
        capabilityStates: {},
        currentTaskId: "task-running-fresh",
        connectedAt: oldDate,
        lastHeartbeatAt: freshHeartbeat,
      },
    ],
    [],
    [
      {
        id: "runtime-fresh-1",
        deviceId: "desktop-1",
        userId: "user-1",
        status: "online",
        connectedAt: oldDate,
        lastHeartbeatAt: freshHeartbeat,
        disconnectedAt: null,
      },
    ],
  ]);
  const published: Array<Record<string, unknown>> = [];
  const app = {
    db,
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
    },
  };

  const result = await reconcileStaleRuntimeTasks(app as never, {
    userId: "user-1",
    now,
  });

  assert.equal(result.reconciled.length, 0);
  assert.equal(db.updates.length, 0);
  assert.equal(db.inserts.length, 0);
  assert.equal(published.length, 0);
});

test("reconcileStaleRuntimeTasks re-dispatches expired planning tasks to a ready runtime", async () => {
  const now = new Date("2030-01-01T00:05:00.000Z");
  const oldDate = new Date("2030-01-01T00:00:00.000Z");
  const freshHeartbeat = new Date("2030-01-01T00:04:45.000Z");
  const db = new SequenceDb([
    [
      {
        id: "task-planning-1",
        userId: "user-1",
        targetDeviceId: "desktop-1",
        title: "Desktop task",
        payload: { prompt: "desktop task body" },
        requestedCapabilities: ["web_research"],
        status: "planning",
        queuePosition: 1,
        summary: null,
        error: null,
        approvalRequest: null,
        result: null,
        runtimeConnectionId: "runtime-old-1",
        dispatchLeaseId: "lease-old-1",
        dispatchLeaseIssuedAt: oldDate,
        dispatchLeaseExpiresAt: new Date("2030-01-01T00:00:45.000Z"),
        dispatchAckAt: null,
        createdAt: oldDate,
        startedAt: null,
        completedAt: null,
        canceledAt: null,
        updatedAt: oldDate,
      },
    ],
    [
      {
        planCode: "pro",
        status: "active",
        trialEndsAt: null,
      },
    ],
    [
      {
        id: "desktop-1",
        type: "desktop",
        externalDeviceId: "elyan-desktop",
        label: "Elyan Desktop",
        platform: "macos",
        runtimeVersion: "1.0.0",
        appVersion: null,
        isActive: true,
        pairedAt: oldDate,
        lastSeenAt: freshHeartbeat,
        createdAt: oldDate,
        updatedAt: oldDate,
      },
    ],
    [
      {
        id: "runtime-active-1",
        deviceId: "desktop-1",
        status: "online",
        capabilities: [],
        capabilityStates: {},
        currentTaskId: null,
        connectedAt: oldDate,
        lastHeartbeatAt: freshHeartbeat,
      },
    ],
    [],
    [
      {
        id: "runtime-active-1",
        deviceId: "desktop-1",
        userId: "user-1",
        status: "online",
        connectedAt: oldDate,
        lastHeartbeatAt: freshHeartbeat,
        disconnectedAt: null,
      },
    ],
    [
      {
        id: "task-planning-1",
        userId: "user-1",
        targetDeviceId: "desktop-1",
        title: "Desktop task",
        payload: { prompt: "desktop task body" },
        requestedCapabilities: ["web_research"],
        status: "planning",
        queuePosition: 1,
        summary: null,
        error: null,
        approvalRequest: null,
        result: null,
        runtimeConnectionId: "runtime-old-1",
        dispatchLeaseId: "lease-old-1",
        dispatchLeaseIssuedAt: oldDate,
        dispatchLeaseExpiresAt: new Date("2030-01-01T00:00:45.000Z"),
        dispatchAckAt: null,
        createdAt: oldDate,
        startedAt: null,
        completedAt: null,
        canceledAt: null,
        updatedAt: oldDate,
      },
    ],
  ]);
  const published: Array<Record<string, unknown>> = [];
  const runtimeDispatches: Array<Record<string, unknown>> = [];
  const app = {
    db,
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
    },
    services: {
      eventBus: {
        publish(event: Record<string, unknown>) {
          published.push(event);
        },
      },
      realtimeHub: {
        sendToRuntime(_deviceId: string, payload: Record<string, unknown>) {
          runtimeDispatches.push(payload);
          return true;
        },
      },
    },
  };

  const result = await reconcileStaleRuntimeTasks(app as never, {
    userId: "user-1",
    now,
  });

  assert.equal(result.reconciled.length, 0);
  assert.equal(db.updates[0]?.status, "planning");
  assert.equal(db.updates[0]?.runtimeConnectionId, "runtime-active-1");
  assert.equal(runtimeDispatches.length, 1);
  assert.equal(runtimeDispatches[0]?.type, "task.dispatch");
  assert.equal(runtimeDispatches[0]?.leaseId != null, true);
  assert.equal(published[0]?.topic, "runtime.leased");
});
