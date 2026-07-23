import assert from "node:assert/strict";
import test from "node:test";
import {
  prepareKnowledgeDocument,
  scoreKnowledgeMatch,
  getBrainProfile,
  shapePublicBrainProfile,
  queueContinuousBrainTrainingJob,
  createModelArtifact,
  summarizeIntegrationApps,
  summarizeWorldContextReadiness,
} from "./service.js";
import { createKnowledgeDocumentBodySchema } from "./schemas.js";
import { worldSignals } from "../../db/schema.js";

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

  limit() {
    return this;
  }

  leftJoin() {
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
  constructor(
    private readonly results: unknown[],
    private readonly inserted: Array<{ table: string; values: Record<string, unknown> }> = [],
  ) {}

  select() {
    const results = this.results;
    return {
      from(table: unknown) {
        return new FakeQuery(table === worldSignals ? [] : results.shift() ?? []);
      },
    };
  }

  insert(table: { _?: string } | Record<string, unknown>) {
    const tableName = typeof table === "object" && table !== null ? "unknown" : "unknown";
    const inserted = this.inserted;
    let currentValues: Record<string, unknown> = {};
    const builder = {
      values(values: Record<string, unknown>) {
        currentValues = values;
        inserted.push({
          table: tableName,
          values,
        });
        return builder;
      },
      returning() {
        const inferredId =
          currentValues["kind"] === "lora" && currentValues["baseModel"]
            ? "queued-training-job-1"
            : currentValues["format"] === "chat_jsonl" && currentValues["recordCount"] !== undefined
              ? "dataset-1"
              : "inserted-row-1";
        return Promise.resolve([
          {
            id: inferredId,
            ...currentValues,
          },
        ]);
      },
      then<TResult1 = unknown[], TResult2 = never>(
        resolve?: ((value: unknown[]) => TResult1 | PromiseLike<TResult1>) | null,
        reject?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
      ) {
        return Promise.resolve([] as unknown[]).then(resolve, reject);
      },
    } as const;

    return builder;
  }
}

async function withMockedFetch<T>(
  handler: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response> | Response,
  run: () => Promise<T>,
) {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = handler as typeof fetch;

  try {
    return await run();
  } finally {
    globalThis.fetch = originalFetch;
  }
}

test("integration readiness derives read tools from actual OAuth grants, not app-level write scopes", () => {
  const readiness = summarizeIntegrationApps(
    [
      {
        id: "gmail",
        displayName: "Gmail",
        serverUrl: "",
        capabilities: ["gmail"],
        configured: true,
        available: true,
        connected: false,
        missingScopes: ["https://www.googleapis.com/auth/gmail.send"],
      },
    ],
    true,
    [
      {
        provider: "google",
        capabilities: ["gmail"],
        scopes: ["https://www.googleapis.com/auth/gmail.readonly"],
      },
    ],
  );

  assert.equal(readiness.ready, true);
  assert.deepEqual(readiness.connectedCapabilities, ["gmail"]);
  assert.deepEqual(readiness.brainReadTools.sort(), ["gmail.read", "gmail.search"]);
  assert.deepEqual(readiness.blockingReasons, []);
  assert.equal(readiness.apps[0]?.connected, false);
  assert.deepEqual(readiness.apps[0]?.missingScopes, [
    "https://www.googleapis.com/auth/gmail.send",
  ]);
});

test("world context readiness exposes only fresh signal kinds and timestamps", () => {
  const now = new Date("2030-01-04T12:00:00.000Z");
  const readiness = summarizeWorldContextReadiness(
    [
      { kind: "health", createdAt: "2030-01-04T10:00:00.000Z" },
      { kind: "location", createdAt: new Date("2030-01-04T11:30:00.000Z") },
      { kind: "calendar", createdAt: "2030-01-04T09:00:00.000Z" },
      { kind: "health", createdAt: "2030-01-04T08:00:00.000Z" },
      { kind: "device", createdAt: "2030-01-01T11:59:59.000Z" },
      { kind: "", createdAt: "2030-01-04T11:00:00.000Z" },
    ],
    72,
    now,
  );

  assert.equal(readiness.ready, true);
  assert.equal(readiness.signalCount, 4);
  assert.deepEqual(readiness.freshKinds, ["calendar", "health", "location"]);
  assert.equal(readiness.latestSignalAt, "2030-01-04T11:30:00.000Z");
  assert.deepEqual(readiness.blockingReasons, []);
});

function mockOllamaTags(models: string[], chatText = "OK") {
  return async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (url.endsWith("/api/tags")) {
      return new Response(JSON.stringify({ models: models.map((name) => ({ name })) }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }

    if (url.endsWith("/api/chat")) {
      return new Response(
        JSON.stringify({
          message: {
            role: "assistant",
            content: chatText,
          },
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    }

    if (url.endsWith("/api/generate")) {
      return new Response(
        JSON.stringify({
          response: chatText,
        }),
        {
          status: 200,
          headers: { "content-type": "application/json" },
        },
      );
    }

    return new Response("{}", {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
}

function makeBrainLatencyRows(count: number) {
  return Array.from({ length: count }, () => [
    {
      status: "success",
      latencyMs: 980,
      metadata: {
        firstDeltaMs: 240,
      },
      createdAt: new Date("2030-01-03T00:05:00.000Z"),
    },
  ]);
}

function makeLearningQualityRow(input: Partial<Record<string, number>> = {}) {
  return [
    {
      thumbsUp: 0,
      thumbsDown: 0,
      regenerate: 0,
      toneSignals: 0,
      humorSignals: 0,
      brevitySignals: 0,
      helpfulnessSignals: 0,
      taskRoutingSignals: 0,
      warmStyleVotes: 0,
      formalStyleVotes: 0,
      balancedStyleVotes: 0,
      ...input,
    },
  ];
}

test("prepareKnowledgeDocument splits long text into stable chunk metadata", () => {
  const prepared = prepareKnowledgeDocument({
    text: [
      "Elyan keeps private local data on the desktop runtime.",
      "The shared brain can serve chat to mobile and desktop without leaking user knowledge.",
      "Learning signals stay scoped per user unless a controlled workflow promotes them.",
    ].join("\n\n"),
  });

  assert.equal(prepared.contentHash.length, 64);
  assert.equal(prepared.chunks.length >= 1, true);
  assert.equal(prepared.summary.includes("desktop runtime"), true);
  assert.equal(prepared.chunks[0]?.tokenEstimate > 0, true);
  assert.equal(prepared.normalization.normalizedChunkCount >= 1, true);
});

test("prepareKnowledgeDocument accepts structured chunk objects and preserves page metadata", () => {
  const prepared = prepareKnowledgeDocument({
    chunks: [
      {
        text: "Sayfa 1: Elyan hızlı ve güvenli çalışır.",
        pageNumber: 1,
        metadata: {
          kind: "pdf_page_text",
          confidence: 0.94,
        },
      },
      {
        content: "Sayfa 2: Structured metadata yine saklanır.",
        pageNumber: 2,
        metadata: {
          kind: "ocr_text",
          sourceLabel: "vision_pass",
        },
      },
    ],
    metadata: {
      source_device_id: "device-1",
      content_hash: "hash-1",
    },
  });

  assert.equal(prepared.chunks.length, 2);
  assert.equal(prepared.chunks[0]?.content.includes("Sayfa 1"), true);
  assert.equal(prepared.chunks[0]?.metadata.pageNumber, 1);
  assert.equal(prepared.chunks[0]?.metadata.chunkKind, "pdf_page_text");
  assert.equal(prepared.chunks[0]?.metadata.source_device_id, "device-1");
  assert.equal(prepared.chunks[1]?.metadata.pageNumber, 2);
  assert.equal(prepared.normalization.structuredChunkCount >= 2, true);
});

test("prepareKnowledgeDocument splits long paragraphs into bounded chunks", () => {
  const prepared = prepareKnowledgeDocument({
    text: `${"Elyan veri okuma ve işleme katmanını daha doğru hale getirir. ".repeat(24)}\n\n${"Aynı paragraf içinde kalan uzun OCR çıktısı da küçük prompt parçalarına ayrılmalıdır. ".repeat(18)}`,
  });

  assert.equal(prepared.chunks.length > 1, true);
  assert.equal(prepared.chunks.every((chunk) => chunk.content.length <= 900), true);
});

test("createKnowledgeDocumentBodySchema requires readable text or chunks", () => {
  assert.throws(
    () =>
      createKnowledgeDocumentBodySchema.parse({
        title: "Broken input",
        sourceType: "manual",
        metadata: {},
      }),
    /text or chunks is required/,
  );

  const parsed = createKnowledgeDocumentBodySchema.parse({
    title: "Readable input",
    sourceType: "manual",
    text: "Merhaba Elyan",
    metadata: {},
  });

  assert.equal(parsed.text, "Merhaba Elyan");
  assert.equal(parsed.chunks, undefined);
});

test("createKnowledgeDocumentBodySchema accepts structured chunk objects", () => {
  const parsed = createKnowledgeDocumentBodySchema.parse({
    title: "Structured input",
    sourceType: "manual",
    chunks: [
      {
        text: "Sayfa 1: cihazda çözümlenmiş içerik",
        pageNumber: 1,
        metadata: {
          kind: "pdf_page_text",
        },
      },
    ],
    metadata: {
      source_device_id: "device-1",
      raw_file_uploaded: false,
      data_origin: "local_derived",
    },
  });

  assert.equal(parsed.chunks?.length, 1);
  const firstChunk = parsed.chunks?.[0] as Record<string, unknown> | undefined;
  assert.equal(firstChunk?.pageNumber, 1);
  assert.equal((firstChunk?.metadata as Record<string, unknown> | undefined)?.kind, "pdf_page_text");
});

test("createKnowledgeDocumentBodySchema rejects raw binary upload hints", () => {
  assert.throws(
    () =>
      createKnowledgeDocumentBodySchema.parse({
        title: "Raw upload",
        sourceType: "manual",
        text: "Okunabilir veri",
        metadata: {
          bytes: "YWJjZA==",
          mimeType: "application/pdf",
        },
      }),
    /raw binary upload payload is not accepted; send text\/chunks only/,
  );

  assert.throws(
    () =>
      createKnowledgeDocumentBodySchema.parse({
        title: "Raw upload data uri",
        sourceType: "manual",
        text: "data:application/pdf;base64,JVBERi0xLjQK",
        metadata: {},
      }),
    /raw binary upload payload is not accepted; send text\/chunks only/,
  );
});

test("prepareKnowledgeDocument redacts obvious secrets and private paths", () => {
  const prepared = prepareKnowledgeDocument({
    text: [
      "My token is sk_test_super_secret_value_1234567890.",
      "Private note: /Users/emrekoca/Desktop/secrets.txt",
      "Safe fact: Elyan keeps user memory local by default.",
    ].join("\n\n"),
  });

  const joined = prepared.chunks.map((chunk) => chunk.content).join("\n");
  assert.equal(joined.includes("sk_test_super_secret_value_1234567890"), false);
  assert.equal(joined.includes("/Users/emrekoca/Desktop/secrets.txt"), false);
  assert.equal(joined.includes("[redacted]"), true);
});

test("prepareKnowledgeDocument deduplicates repeated chunks and records normalization stats", () => {
  const prepared = prepareKnowledgeDocument({
    chunks: [
      "Chunk A keeps Elyan fast.",
      "Chunk A keeps Elyan fast.",
      "Chunk B keeps memory clean.",
      "Chunk B keeps memory clean.",
    ],
  });

  assert.equal(prepared.chunks.length, 2);
  assert.equal(prepared.normalization.sourceChunkCount, 4);
  assert.equal(prepared.normalization.normalizedChunkCount, 2);
  assert.equal(prepared.normalization.duplicateChunkCount, 2);
  assert.equal(prepared.normalization.compressionRatio <= 1, true);
});

test("prepareKnowledgeDocument detects likely language tags when they are omitted", () => {
  const prepared = prepareKnowledgeDocument({
    text: "Merhaba Elyan, kullanıcı notlarını güvenli ve kısa cümlelerle öğren.",
  });

  assert.equal(prepared.languageTags.includes("tr"), true);
});

test("scoreKnowledgeMatch prefers exact user-scoped results", () => {
  const sharedScore = scoreKnowledgeMatch("local model api", {
    title: "Shared Brain",
    content: "The shared brain can expose a local model API for chat.",
    scope: "shared",
    ordinal: 0,
  });
  const userScore = scoreKnowledgeMatch("local model api", {
    title: "My Local Brain",
    content: "My local model api serves private personalized chat responses.",
    scope: "user",
    ordinal: 0,
  });

  assert.equal(userScore > sharedScore, true);
});

test("shapePublicBrainProfile removes backend-private model gateway fields", () => {
  const publicProfile = shapePublicBrainProfile({
    chat: {
      dispatchPath: "/v1/tasks",
      brainProfilePath: "/v1/brain/profile",
      realtimePath: "/v1/realtime/stream",
      sessionsPath: "/v1/chat/sessions",
      messagesPath: "/v1/chat/messages",
      homeSurface: "chat",
      serverTargetDeviceId: "shared-brain-device",
      activeSharedModel: {
        id: "shared-model-1",
        name: "Shared Mixtral",
        provider: "openrouter",
        scope: "shared",
      },
      activeUserModel: {
        id: "user-model-1",
        name: "User Llama",
        provider: "ollama",
        scope: "user",
      },
      inferenceReady: true,
      isChatUsable: true,
      modelMode: "adapted",
      trainingState: "base_serving",
      configuredBaseModel: "llama3.2",
      resolvedBaseModel: "mixtral",
      resolvedBaseModelSource: "artifact",
      availableModels: ["mixtral", "llama3.2"],
      warmupJobId: "warmup-job-1",
      serverBrainName: "Elyan",
      connection: {
        mode: "desktop_first_then_server_brain",
        desktopAvailable: true,
        mobileAvailable: true,
        connectedDesktopDevices: 1,
        inferenceReady: true,
        serverBrainReady: true,
        fallbackRoute: "server_brain_unavailable",
      },
      dispatchPathValid: true,
      realtimePathValid: true,
      brainProfilePathValid: true,
      messagesPathValid: true,
    },
    skills: {
      enabled: true,
      catalogVersion: "2026-06-skill-catalog-v1",
      items: [
        {
          id: "document_summary",
          version: "1.0.0",
          displayName: "Özetle",
          displayDescription: "Eklenen belge veya görselden kısa özet çıkarır.",
          slashCommand: "/özetle",
          uiCategory: "document",
          requiresAttachment: true,
          supportedMimeTypes: ["application/pdf"],
          manualSelectable: true,
        },
      ],
    },
    integrations: {
      ready: true,
      connectorToolsEnabled: true,
      connectedCapabilities: ["email"],
      brainReadTools: ["gmail.search", "gmail.read"],
      blockingReasons: [],
      apps: [
        {
          id: "gmail",
          displayName: "Gmail",
          execution: "server_connector",
          capabilities: ["email"],
          configured: true,
          available: true,
          connected: true,
          missingScopes: [],
          probeStatus: null,
          probeErrorCode: null,
          probeToolCount: null,
          provider: "google",
        },
      ],
    },
    quantum: null,
    retrieval: {
      readyDocuments: 0,
      readyChunks: 0,
    },
    learning: {
      userUnderstandingEnabled: true,
      personalizationEnabled: false,
    },
    training: {
      queuedJobs: 0,
      runningJobs: 0,
      readyDatasets: 0,
      totalDatasets: 0,
      safeLearningEvents: 0,
      connectivity: {
        mobileDevices: 0,
        desktopDevices: 1,
        connectedDesktopDevices: 1,
        bridgeMode: "mobile_desktop_sync",
        bridgeTargets: [],
      },
      signalSummary: {
        interactionEvents: 0,
        feedbackEvents: 0,
        runtimeEvents: 0,
        systemEvents: 0,
        routingSignals: 0,
        bridgeSignals: 0,
      },
      pipeline: {
        neural: null,
        activeJobId: null,
        activeJobStatus: null,
        activeJobKind: null,
        activeJobBaseModel: "llama3.2",
        activeJobPlan: null,
        activeModelId: null,
        activeModelScope: null,
        activeModelAdapter: "base",
        bridgeReadiness: true,
        bridgeLearning: {
          routingSignals: 0,
          bridgeSignals: 0,
          mobileDevices: 0,
          desktopDevices: 0,
          connectedDesktopDevices: 1,
        },
        continuousImprovement: {
          status: "collecting_signals",
          canQueue: false,
          activeSharedJobId: null,
          activeSharedJobStatus: null,
          activeSharedModelId: null,
          activeUserModelId: null,
          readyDatasets: 0,
          safeLearningEvents: 0,
          nextAction: "queue_shared_refresh",
        },
        routingQuality: {
          score: 0,
          state: "cold_start",
          totalSignals: 0,
          bridgeReadiness: true,
          runtimeReady: true,
          readyForPromotion: false,
        },
        promotion: {
          readySharedModelCount: 1,
          activeSharedModelId: "shared-model-1",
          activeSharedModelProvider: "openrouter",
          activeSharedModelAdapter: "base",
          rollbackSharedModelId: null,
          rollbackSharedModelUpdatedAt: null,
          promotedAt: null,
          evaluationState: "bounded_offline_eval",
        },
        inferenceReady: true,
        runtimeReady: true,
      },
      brainLatency: {
        lastChatLatencyMs: null,
        lastStreamingFirstDeltaMs: null,
        recentBrainTimeoutCount: 0,
        lastBrainResponseAt: null,
      },
    },
    quota: null,
    bridge: {
      mode: "desktop_first_then_server_brain",
      taskRouting: "desktop_first_when_available",
      chatRouting: "server_brain_first",
      desktopAvailable: true,
      mobileAvailable: true,
      connectedDesktopDevices: 1,
      serverBrainReady: true,
      fallbackRoute: "server_brain_unavailable",
      surfaces: {
        chatMessages: "/v1/chat/messages",
        tasks: "/v1/tasks",
        realtime: "/v1/realtime/stream",
      },
    },
  } as never);

  const sanitizedChat = publicProfile.chat as any;

  assert.equal(sanitizedChat.configuredBaseModel, undefined);
  assert.equal(sanitizedChat.resolvedBaseModel, undefined);
  assert.equal(sanitizedChat.resolvedBaseModelSource, undefined);
  assert.equal(sanitizedChat.availableModels, undefined);
  assert.equal(sanitizedChat.activeSharedModel?.provider, undefined);
  assert.equal(sanitizedChat.activeUserModel?.provider, undefined);
  assert.equal(sanitizedChat.activeMobileDefaultProfile, undefined);
  assert.equal(sanitizedChat.fallbackStatus, undefined);
  assert.equal(sanitizedChat.currentServingPolicy, undefined);
  assert.equal(sanitizedChat.activeArtifact, undefined);
  assert.equal(sanitizedChat.activeSharedModel?.label, "Elyan paylaşılan zeka");
  assert.equal(sanitizedChat.activeUserModel?.label, "Elyan kişisel zeka");
  assert.equal(publicProfile.skills.enabled, true);
  assert.equal(publicProfile.skills.items[0]?.slashCommand, "/özetle");
  assert.equal(JSON.stringify(publicProfile.skills).includes("instructions"), false);
  assert.equal(publicProfile.integrations.ready, true);
  assert.deepEqual(publicProfile.integrations.connectedCapabilities, ["email"]);
  assert.deepEqual(publicProfile.integrations.brainReadTools, ["gmail.search", "gmail.read"]);
  assert.equal((publicProfile.integrations.apps[0] as any).provider, undefined);
  const publicPayload = JSON.stringify(publicProfile).toLowerCase();
  assert.equal(publicPayload.includes("openrouter"), false);
  assert.equal(publicPayload.includes("ollama"), false);
  assert.equal(publicPayload.includes("mixtral"), false);
  assert.equal(publicPayload.includes("llama3.2"), false);
  assert.equal(publicPayload.includes("provider"), false);
});

test("getBrainProfile exposes the stable mobile and desktop contract surface", async () => {
  const app = {
    db: new FakeDb([
      [
        {
          id: "shared-model-1",
          name: "Shared Mixtral",
          scope: "shared",
          provider: "openrouter",
          baseModel: "mixtral",
          adapterKind: "openai_compatible",
          status: "ready",
          storageUri: "s3://models/shared-model-1",
          checksum: "sha256:shared-model-1",
          updatedAt: new Date("2030-01-01T00:00:00.000Z"),
          metadata: {},
        },
        {
          id: "user-model-1",
          name: "User Llama",
          scope: "user",
          provider: "ollama",
          baseModel: "llama3.2",
          adapterKind: "local",
          status: "ready",
          storageUri: "file:///models/user-model-1",
          checksum: "sha256:user-model-1",
          updatedAt: new Date("2030-01-02T00:00:00.000Z"),
          metadata: {},
        },
      ],
      [{ documents: 12, chunks: 144 }],
      [{ queued: 2, running: 1 }],
      [{ ready: 3, total: 5 }],
      [
        {
          safeEvents: 64,
          interactionEvents: 12,
          feedbackEvents: 6,
          runtimeEvents: 4,
          systemEvents: 2,
          routingSignals: 7,
          bridgeSignals: 5,
        },
      ],
      makeLearningQualityRow({
        thumbsUp: 8,
        thumbsDown: 2,
        regenerate: 1,
        toneSignals: 3,
        humorSignals: 1,
        brevitySignals: 2,
        helpfulnessSignals: 4,
        taskRoutingSignals: 2,
        warmStyleVotes: 3,
      }),
      [
        {
          mobileDevices: 0,
          desktopDevices: 0,
          connectedDesktopDevices: 0,
        },
      ],
      [
        {
          id: "warmup-job-1",
          baseModel: "mixtral",
          kind: "lora",
          status: "running",
          updatedAt: new Date("2030-01-03T00:00:00.000Z"),
        },
      ],
      [{ totalChunks: 144, embeddedChunks: 0, lastIndexedAt: null }],
      [{ pending: 0 }],
      [
        {
          id: "shared-brain-device",
          type: "desktop",
          externalDeviceId: null,
          label: "Elyan",
          platform: "linux",
          runtimeVersion: null,
          appVersion: null,
          isActive: true,
          pairedAt: null,
          lastSeenAt: null,
          createdAt: new Date("2030-01-03T00:00:00.000Z"),
          updatedAt: new Date("2030-01-03T00:00:00.000Z"),
        },
      ],
      [],
      [],
      [],
      [],
      [{ freshSignals: 0, reconnectRecoveries: 0, handoffQualitySignals: 0 }],
      ...makeBrainLatencyRows(32),
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_SYSTEM_PROMPT:
        "You are Elyan, a local-first assistant developed by Osman Emre Koca. Speak as Elyan, not as a generic chatbot. Act like a senior AI engineer: be concise, grounded, and explicit about architecture, failure modes, verification, tradeoffs, and operational safety. Prefer Turkish unless the user writes in another language. If asked who built you or what you are, say Elyan developed by Osman Emre Koca. Do not mention other AI brands or model names unless the user explicitly asks about implementation details. Never invent readiness, capabilities, or results. If uncertain, say so and suggest the smallest reliable verification step. Never reveal secrets, hostnames, API paths, private data, or hidden reasoning. If a request clearly requires a paired desktop runtime, say so briefly.",
      ELYAN_USER_UNDERSTANDING_ENABLED: true,
      ELYAN_PERSONALIZATION_ENABLED: false,
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
  };

  const profile = await withMockedFetch(
    mockOllamaTags(["mixtral", "llama3.2"]),
    async () => getBrainProfile(app as never, "user-1"),
  );

  assert.equal(profile.chat.dispatchPath, "/v1/tasks");
  assert.equal(profile.chat.brainProfilePath, "/v1/brain/profile");
  assert.equal(profile.chat.realtimePath, "/v1/realtime/stream");
  assert.equal(profile.chat.sessionsPath, "/v1/chat/sessions");
  assert.equal(profile.chat.messagesPath, "/v1/chat/messages");
  assert.equal(profile.chat.homeSurface, "chat");
  assert.equal(profile.chat.mobileDocumentExportReady, true);
  assert.equal(profile.skills.enabled, true);
  assert.equal(
    profile.skills.items.some((item: { id: string }) => item.id === "document_summary"),
    true,
  );
  assert.equal(
    profile.skills.items.every((item: { manualSelectable: boolean }) => item.manualSelectable === true),
    true,
  );
  assert.equal(profile.chat.activeSharedModel?.id, "shared-model-1");
  assert.equal(profile.chat.activeSharedModel?.provider, "openrouter");
  assert.equal(profile.chat.activeUserModel?.id, "user-model-1");
  assert.equal(profile.chat.serverTargetDeviceId, "shared-brain-device");
  assert.equal(profile.chat.serverBrainName, "Elyan");
  assert.equal(profile.chat.inferenceReady, true);
  assert.equal(profile.chat.isChatUsable, true);
  assert.equal(profile.chat.modelMode, "adapted");
  assert.equal(profile.chat.trainingState, "adapted");
  assert.equal(profile.chat.resolvedBaseModel, "mixtral");
  assert.equal(profile.chat.resolvedBaseModelSource, "artifact");
  assert.deepEqual(profile.chat.availableModels, ["mixtral", "llama3.2"]);
  assert.equal(profile.sections.runtime.sharedBrainCapabilitySummary?.total, 0);
  assert.equal(profile.sections.model.resolvedBaseModel, "mixtral");
  assert.equal(profile.sections.routing.task, "desktop_first_when_available");
  assert.equal(profile.chat.warmupJobId, "warmup-job-1");
  assert.equal(profile.chat.connection.mode, "desktop_first_then_server_brain");
  assert.equal(profile.chat.connection.desktopAvailable, false);
  assert.equal(profile.chat.connection.mobileAvailable, false);
  assert.equal(profile.chat.connection.connectedDesktopDevices, 0);
  assert.equal(profile.chat.connection.serverBrainReady, true);
  assert.equal(profile.bridge.mode, "desktop_first_then_server_brain");
  assert.equal(profile.bridge.taskRouting, "desktop_first_when_available");
  assert.equal(profile.bridge.chatRouting, "server_brain_first");
  assert.equal(profile.bridge.desktopAvailable, false);
  assert.equal(profile.bridge.mobileAvailable, false);
  assert.equal(profile.bridge.connectedDesktopDevices, 0);
  assert.equal(profile.bridge.serverBrainReady, true);
  assert.equal(profile.quota.mode, "identity_window");
  assert.equal(profile.quota.commitPoint, "task.create+brain.inference");
  assert.equal(profile.quota.consumptionMetric, "budget_units");
  assert.deepEqual(profile.quota.appliesTo, ["chat", "task", "document_upload", "image_upload"]);
  assert.deepEqual(profile.quota.safeErrorCodes, [
    "five_hour_quota_reached",
    "daily_quota_reached",
    "weekly_quota_reached",
    "document_quota_reached",
    "image_quota_reached",
    "server_brain_unavailable",
  ]);
  assert.equal(profile.learning.userUnderstandingEnabled, true);
  assert.equal(profile.learning.personalizationEnabled, false);
  assert.equal(profile.learning.extractionEnabled, true);
  assert.equal(profile.learning.qualityGate.status, "ready_for_queue");
  assert.equal(profile.learning.qualityGate.reasons.length, 0);
  assert.equal(profile.learning.responseStylePreference.code, "warm");
  assert.deepEqual(profile.memory.workingMemoryBudget, {
    maxConversationMessages: 6,
    maxPromptTokens: 900,
    maxMemoryHints: 8,
  });
  assert.equal(profile.memory.episodicMemoryCount, 0);
  assert.equal(profile.memory.selfModelMemoryCount, 0);
  assert.equal(profile.memory.reflectiveMemoryCount, 0);
  assert.equal(profile.memory.softDeletedCount, 0);
  assert.equal(profile.memory.lastSelfModelUpdatedAt, null);
  assert.equal(profile.metacognition.memoryAwareChatReady, false);
  assert.equal(profile.metacognition.memoryConflictGuardReady, false);
  assert.equal(profile.metacognition.selfModelReady, false);
  assert.equal(profile.metacognition.reflectiveMemoryReady, false);
  assert.equal(profile.metacognition.memoryControlReady, false);
  assert.equal(profile.memory.recallReady, false);
  assert.equal(profile.memory.activeSemanticCount, 0);
  assert.equal(profile.retrieval.readyDocuments, 12);
  assert.equal(profile.retrieval.readyChunks, 144);
  assert.equal(profile.retrieval.memoryIndexCoverage, 0);
  assert.equal(profile.retrieval.memoryRecallMode, "lexical_memory_fallback");
  assert.equal(profile.training.queuedJobs, 2);
  assert.equal(profile.training.runningJobs, 1);
  assert.equal(profile.training.readyDatasets, 3);
  assert.equal(profile.training.totalDatasets, 5);
  assert.equal(profile.training.safeLearningEvents, 64);
  assert.equal(profile.training.connectivity.mobileDevices, 0);
  assert.equal(profile.training.connectivity.desktopDevices, 0);
  assert.equal(profile.training.connectivity.connectedDesktopDevices, 0);
  assert.equal(profile.training.connectivity.bridgeMode, "mobile_desktop_sync");
  assert.equal(profile.training.pipeline.bridgeReadiness, false);
  assert.equal(profile.training.signalSummary.interactionEvents, 12);
  assert.equal(profile.training.signalSummary.feedbackEvents, 6);
  assert.equal(profile.training.signalSummary.runtimeEvents, 4);
  assert.equal(profile.training.signalSummary.systemEvents, 2);
  assert.equal(profile.training.signalSummary.routingSignals, 7);
  assert.equal(profile.training.signalSummary.bridgeSignals, 5);
  assert.equal(profile.training.qualitySignalSummary.helpfulnessSignals, 4);
  assert.equal(profile.training.queueEligibility.status, "ready_for_queue");
  assert.equal(profile.training.promotionEligibility.status, "ready");
  assert.equal(profile.training.pipeline.runtimeReady, true);
  assert.equal(profile.training.pipeline.bridgeLearning.routingSignals, 7);
  assert.equal(profile.training.pipeline.bridgeLearning.bridgeSignals, 5);
  assert.equal(profile.training.pipeline.continuousImprovement.status, "active");
  assert.equal(profile.training.pipeline.continuousImprovement.canQueue, false);
  assert.equal(profile.training.pipeline.continuousImprovement.activeSharedJobId, "warmup-job-1");
  assert.equal(profile.training.pipeline.continuousImprovement.activeSharedModelId, "shared-model-1");
  assert.equal(profile.training.pipeline.continuousImprovement.readyDatasets, 3);
  assert.equal(profile.training.pipeline.continuousImprovement.safeLearningEvents, 64);
  assert.equal(profile.training.pipeline.continuousImprovement.nextAction, "wait_for_active_job");
  assert.equal(profile.training.pipeline.queueGateStatus, "ready_for_queue");
  assert.equal(profile.training.pipeline.promotionGateStatus, "ready");
  assert.equal(profile.training.pipeline.routingQuality.score, 0.6);
  assert.equal(profile.training.pipeline.routingQuality.state, "building");
  assert.equal(profile.training.pipeline.routingQuality.totalSignals, 12);
  assert.equal(profile.training.pipeline.routingQuality.bridgeReadiness, false);
  assert.equal(profile.training.pipeline.routingQuality.runtimeReady, true);
  assert.equal(profile.training.pipeline.routingQuality.readyForPromotion, false);
  assert.equal(profile.training.brainLatency.lastChatLatencyMs, 980);
  assert.equal(profile.training.brainLatency.lastStreamingFirstDeltaMs, 240);
  assert.equal(profile.training.brainLatency.recentBrainTimeoutCount, 0);
  assert.equal(profile.training.brainLatency.lastBrainResponseAt, "2030-01-03T00:05:00.000Z");
  assert.equal(profile.chat.activeMobileDefaultProfile.workload, "mobile_chat_fast");
  assert.equal(profile.chat.activeMobileDefaultProfile.mode, "fast_first_local_only");
  assert.equal(profile.chat.activeMobileDefaultProfile.model, "mixtral");
  assert.equal(profile.chat.latencyBudgets.mobileChatFastTimeoutMs, 7000);
  assert.equal(profile.chat.workloadProfiles.mobileChatFast.maxTokens, 384);
  assert.equal(profile.chat.responseProtocol.qualityRepairReady, true);
  assert.equal(profile.chat.responseProtocol.mobileChatQualityEvalReady, true);
  assert.equal(profile.chat.responseProtocol.trainingLoopReady, true);
  assert.equal(profile.chat.fallbackStatus.hostedConfigured, false);
  assert.equal(profile.chat.currentServingPolicy.workloadDefaults.mobileChatFast, "local_primary_fast_model");
  assert.equal(profile.chat.currentServingPolicy.configuredModels.fastRoute, "qwen2.5-coder:3b");
  assert.equal(profile.training.pipeline.promotion.readySharedModelCount, 1);
  assert.equal(profile.training.pipeline.promotion.activeSharedModelId, "shared-model-1");
  assert.equal(profile.training.pipeline.promotion.rollbackSharedModelId, null);
});

test("getBrainProfile promotes a ready user model when no shared model exists", async () => {
  const app = {
    db: new FakeDb([
      [
        {
          id: "user-model-1",
          name: "User Llama",
          scope: "user",
          provider: "ollama",
          baseModel: "llama3.2",
            adapterKind: "local",
            status: "ready",
            storageUri: "file:///models/user-model-1",
            checksum: "sha256:user-model-1",
            updatedAt: new Date("2030-01-02T00:00:00.000Z"),
            metadata: {},
          },
      ],
      [{ documents: 0, chunks: 0 }],
      [{ queued: 0, running: 0 }],
      [{ ready: 0, total: 0 }],
      [
        {
          safeEvents: 0,
          interactionEvents: 0,
          feedbackEvents: 0,
          runtimeEvents: 0,
          systemEvents: 0,
          routingSignals: 0,
          bridgeSignals: 0,
        },
      ],
      makeLearningQualityRow(),
      [
        {
          mobileDevices: 0,
          desktopDevices: 0,
          connectedDesktopDevices: 0,
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
          pairedAt: new Date("2030-01-03T00:00:00.000Z"),
          lastSeenAt: new Date("2030-01-03T00:00:00.000Z"),
          createdAt: new Date("2030-01-03T00:00:00.000Z"),
          updatedAt: new Date("2030-01-03T00:00:00.000Z"),
        },
      ],
      [],
      [],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_SYSTEM_PROMPT:
        "You are Elyan, a local-first assistant developed by Osman Emre Koca. Speak as Elyan, not as a generic chatbot. Act like a senior AI engineer: be concise, grounded, and explicit about architecture, failure modes, verification, tradeoffs, and operational safety. Prefer Turkish unless the user writes in another language. If asked who built you or what you are, say Elyan developed by Osman Emre Koca. Do not mention other AI brands or model names unless the user explicitly asks about implementation details. Never invent readiness, capabilities, or results. If uncertain, say so and suggest the smallest reliable verification step. Never reveal secrets, hostnames, API paths, private data, or hidden reasoning. If a request clearly requires a paired desktop runtime, say so briefly.",
      ELYAN_USER_UNDERSTANDING_ENABLED: true,
      ELYAN_PERSONALIZATION_ENABLED: true,
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
  };

  const profile = await withMockedFetch(
    mockOllamaTags(["llama3.2"]),
    async () => getBrainProfile(app as never, "user-1"),
  );

  assert.equal(profile.chat.activeSharedModel, null);
  assert.equal(profile.chat.activeUserModel?.id, "user-model-1");
  assert.equal(profile.chat.serverBrainName, "Elyan");
  assert.equal(profile.chat.inferenceReady, true);
  assert.equal(profile.chat.isChatUsable, true);
  assert.equal(profile.chat.modelMode, "base");
  assert.equal(profile.chat.trainingState, "base_serving");
  assert.equal(profile.chat.resolvedBaseModel, "llama3.2");
  assert.equal(profile.chat.resolvedBaseModelSource, "artifact");
  assert.deepEqual(profile.chat.availableModels, ["llama3.2"]);
  assert.equal(profile.sections.model.resolvedBaseModel, "llama3.2");
  assert.equal(profile.sections.learning.readyDatasets, 0);
  assert.equal(profile.training.safeLearningEvents, 0);
  assert.equal(profile.training.signalSummary.routingSignals, 0);
  assert.equal(profile.training.signalSummary.bridgeSignals, 0);
  assert.equal(profile.training.pipeline.bridgeLearning.routingSignals, 0);
  assert.equal(profile.training.pipeline.bridgeLearning.bridgeSignals, 0);
  assert.equal(profile.training.pipeline.continuousImprovement.status, "collecting_signals");
  assert.equal(profile.training.pipeline.continuousImprovement.canQueue, false);
  assert.equal(profile.training.pipeline.continuousImprovement.activeSharedJobId, null);
  assert.equal(profile.training.pipeline.continuousImprovement.readyDatasets, 0);
  assert.equal(profile.training.pipeline.continuousImprovement.safeLearningEvents, 0);
  assert.equal(profile.training.pipeline.continuousImprovement.nextAction, "collect_quality_signals");
  assert.equal(profile.training.queueEligibility.status, "blocked_low_signal");
  assert.equal(profile.training.pipeline.routingQuality.score, 0);
  assert.equal(profile.training.pipeline.routingQuality.state, "cold_start");
  assert.equal(profile.training.pipeline.routingQuality.totalSignals, 0);
  assert.equal(profile.training.pipeline.routingQuality.bridgeReadiness, false);
  assert.equal(profile.training.pipeline.routingQuality.runtimeReady, true);
  assert.equal(profile.training.pipeline.routingQuality.readyForPromotion, false);
});

test("getBrainProfile keeps server chat usable without a desktop target when inference is healthy", async () => {
  const app = {
    db: new FakeDb([
      [],
      [{ documents: 0, chunks: 0 }],
      [{ queued: 0, running: 0 }],
      [{ ready: 0, total: 0 }],
      [
        {
          safeEvents: 0,
          interactionEvents: 0,
          feedbackEvents: 0,
          runtimeEvents: 0,
          systemEvents: 0,
          routingSignals: 0,
          bridgeSignals: 0,
        },
      ],
      makeLearningQualityRow(),
      [
        {
          mobileDevices: 1,
          desktopDevices: 0,
          connectedDesktopDevices: 0,
        },
      ],
      [],
      [],
      [],
      [
        {
          status: "success",
          latencyMs: 620,
          metadata: {
            firstDeltaMs: 180,
          },
          createdAt: new Date("2030-01-03T00:05:00.000Z"),
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_SYSTEM_PROMPT: "System prompt",
      ELYAN_USER_UNDERSTANDING_ENABLED: true,
      ELYAN_PERSONALIZATION_ENABLED: true,
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
  };

  const profile = await withMockedFetch(
    mockOllamaTags(["llama3.2"], "OK"),
    async () => getBrainProfile(app as never, "user-1"),
  );

  assert.equal(profile.chat.serverTargetDeviceId, null);
  assert.equal(profile.chat.inferenceReady, true);
  assert.equal(profile.chat.isChatUsable, true);
  assert.equal(profile.bridge.serverBrainReady, true);
  assert.equal(profile.chat.connection.serverBrainReady, true);
});

test("getBrainProfile keeps chat available when runtime is reachable even if the live probe returns empty", async () => {
  const app = {
    db: new FakeDb([
      [],
      [{ documents: 0, chunks: 0 }],
      [{ queued: 0, running: 0 }],
      [{ ready: 0, total: 0 }],
      [
        {
          safeEvents: 0,
          interactionEvents: 0,
          feedbackEvents: 0,
          runtimeEvents: 0,
          systemEvents: 0,
          routingSignals: 0,
          bridgeSignals: 0,
        },
      ],
      makeLearningQualityRow(),
      [
        {
          mobileDevices: 0,
          desktopDevices: 0,
          connectedDesktopDevices: 0,
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
          pairedAt: new Date("2030-01-03T00:00:00.000Z"),
          lastSeenAt: new Date("2030-01-03T00:00:00.000Z"),
          createdAt: new Date("2030-01-03T00:00:00.000Z"),
          updatedAt: new Date("2030-01-03T00:00:00.000Z"),
        },
      ],
      [],
      [],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_SYSTEM_PROMPT: "System prompt",
      ELYAN_USER_UNDERSTANDING_ENABLED: true,
      ELYAN_PERSONALIZATION_ENABLED: true,
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
      ELYAN_SHARED_BRAIN_KEEP_ALIVE: "30m",
    },
  };

  const profile = await withMockedFetch(
    mockOllamaTags(["llama3.2"], ""),
    async () => getBrainProfile(app as never, "user-1"),
  );

  assert.equal(profile.chat.modelMode, "base");
  assert.equal(profile.chat.trainingState, "base_serving");
  assert.equal(profile.chat.inferenceReady, true);
  assert.equal(profile.chat.isChatUsable, true);
  assert.equal(profile.chat.connection.serverBrainReady, true);
});

test("queueContinuousBrainTrainingJob queues only with approved correction lineage and benchmark baseline", async () => {
  const inserted: Array<{ table: string; values: Record<string, unknown> }> = [];
  const app = {
    db: new FakeDb(
      [
        [
          {
            id: "user-model-1",
            name: "User Llama",
            scope: "user",
            provider: "ollama",
            baseModel: "llama3.2",
            adapterKind: "local",
            status: "ready",
            storageUri: "file:///models/user-model-1",
            checksum: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            updatedAt: new Date("2030-01-02T00:00:00.000Z"),
            metadata: {},
          },
        ],
        [{ documents: 0, chunks: 0 }],
        [{ queued: 0, running: 0 }],
        [{ ready: 0, total: 0 }],
      [
        {
          safeEvents: 64,
            interactionEvents: 24,
            feedbackEvents: 12,
            runtimeEvents: 8,
            systemEvents: 4,
            routingSignals: 14,
          bridgeSignals: 10,
        },
      ],
      makeLearningQualityRow({
        thumbsUp: 9,
        thumbsDown: 1,
        regenerate: 1,
        toneSignals: 3,
        humorSignals: 1,
        brevitySignals: 2,
        helpfulnessSignals: 4,
        taskRoutingSignals: 2,
        balancedStyleVotes: 2,
      }),
      [
        {
          mobileDevices: 0,
            desktopDevices: 0,
            connectedDesktopDevices: 0,
          },
        ],
        [],
      [{ totalChunks: 0, embeddedChunks: 0, lastIndexedAt: null }],
      [{ pending: 0 }],
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
            pairedAt: new Date("2030-01-03T00:00:00.000Z"),
            lastSeenAt: new Date("2030-01-03T00:00:00.000Z"),
            createdAt: new Date("2030-01-03T00:00:00.000Z"),
            updatedAt: new Date("2030-01-03T00:00:00.000Z"),
        },
      ],
      [],
      [],
      [],
      [{ freshSignals: 0, reconnectRecoveries: 0, handoffQualitySignals: 0 }],
      [],
      [],
      [
        {
          id: "dataset-1",
          status: "ready",
          metadata: {
            datasetRole: "sft_ready_corrections_jsonl",
            datasetVersion: "dataset-v1",
            approvedCorrectionsOnly: true,
            sourceLineage: "approved_corrections",
          },
        },
      ],
      [
        {
          id: "dataset-1",
          status: "ready",
          metadata: {
            datasetRole: "sft_ready_corrections_jsonl",
            datasetVersion: "dataset-v1",
            approvedCorrectionsOnly: true,
            sourceLineage: "approved_corrections",
          },
        },
      ],
      [
        {
          createdAt: new Date("2030-01-03T00:06:00.000Z"),
          payload: {
            status: "pass",
            overallScore: 0.91,
            boundaryScore: 1,
            reasoningScore: 0.82,
            clarificationScore: 0.95,
            toolUseScore: 1,
            latencyScore: 0.7,
            caseCount: 60,
          },
        },
      ],
      [
        {
          id: "dataset-1",
          status: "ready",
          metadata: {
            datasetRole: "sft_ready_corrections_jsonl",
            datasetVersion: "dataset-v1",
            approvedCorrectionsOnly: true,
            sourceLineage: "approved_corrections",
          },
        },
      ],
      [
        {
          id: "dataset-1",
          status: "ready",
          metadata: {
            datasetRole: "sft_ready_corrections_jsonl",
            datasetVersion: "dataset-v1",
            approvedCorrectionsOnly: true,
            sourceLineage: "approved_corrections",
          },
        },
      ],
      [
        {
          createdAt: new Date("2030-01-03T00:06:00.000Z"),
          payload: {
            status: "pass",
            overallScore: 0.91,
            boundaryScore: 1,
            reasoningScore: 0.82,
            clarificationScore: 0.95,
            toolUseScore: 1,
            latencyScore: 0.7,
            caseCount: 60,
          },
        },
      ],
      [
        {
          id: "dataset-1",
          status: "ready",
          metadata: {
            datasetRole: "sft_ready_corrections_jsonl",
            datasetVersion: "dataset-v1",
            approvedCorrectionsOnly: true,
            sourceLineage: "approved_corrections",
          },
        },
      ],
      ],
      inserted,
    ),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_SYSTEM_PROMPT:
        "You are Elyan, a local-first assistant developed by Osman Emre Koca. Speak as Elyan, not as a generic chatbot. Act like a senior AI engineer: be concise, grounded, and explicit about architecture, failure modes, verification, tradeoffs, and operational safety. Prefer Turkish unless the user writes in another language. If asked who built you or what you are, say Elyan developed by Osman Emre Koca. Do not mention other AI brands or model names unless the user explicitly asks about implementation details. Never invent readiness, capabilities, or results. If uncertain, say so and suggest the smallest reliable verification step. Never reveal secrets, hostnames, API paths, private data, or hidden reasoning. If a request clearly requires a paired desktop runtime, say so briefly.",
      ELYAN_USER_UNDERSTANDING_ENABLED: true,
      ELYAN_PERSONALIZATION_ENABLED: true,
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
      ELYAN_WEIGHT_TRAINING_ENABLED: true,
    },
  };

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("{}", { status: 200 });

  try {
    const result = await queueContinuousBrainTrainingJob(app as never, {
      userId: "user-1",
      requestId: "req-1",
      ipAddress: "127.0.0.1",
      userAgent: "test-agent",
    });

    assert.equal(result.created, true);
    assert.equal(result.reason, "queued_shared_refresh");
    assert.equal(result.job?.id, "queued-training-job-1");
    assert.equal(result.elyanModel?.modelName, "Elyan");
    assert.equal(result.elyanModel?.stage, "shadow_evaluation");
    assert.equal(result.elyanProviderPlan?.logicalProvider, "elyan");
    assert.equal(result.elyanProviderPlan?.liveRoutingEnabled, false);
    assert.equal(result.elyanProviderPlan?.traffic.elyanShadowPercent, 100);
    assert.equal(inserted.some((entry) => entry.values["name"] === "Elyan shared LoRA training set"), false);
    assert.equal(inserted.some((entry) => entry.values["name"] === "Elyan continuous brain refresh"), true);
    const trainingInsert = inserted.find((entry) => entry.values["name"] === "Elyan continuous brain refresh");
    const trainingConfig =
      trainingInsert?.values["config"] && typeof trainingInsert.values["config"] === "object"
        ? (trainingInsert.values["config"] as Record<string, unknown>)
        : {};
    const providerStrategy =
      trainingConfig["providerStrategy"] && typeof trainingConfig["providerStrategy"] === "object"
        ? (trainingConfig["providerStrategy"] as Record<string, unknown>)
        : {};
    assert.equal(providerStrategy["learningProvider"], "elyan");
    assert.equal(providerStrategy["servingStrategy"], "groq_primary_elyan_shadow");
    assert.equal(providerStrategy["liveRoutingEnabled"], false);
    assert.equal(providerStrategy["routeReason"], "shadow_eval_only");
    assert.equal(providerStrategy["retirementPolicy"], "operator_approval_after_eval_benchmark_latency_gates");
    assert.equal(
      Array.isArray(providerStrategy["fallback"]) &&
        providerStrategy["fallback"].includes("elyan_shadow_until_quality_gate"),
      true,
    );
    assert.equal(
      trainingConfig["elyanModel"] &&
        typeof trainingConfig["elyanModel"] === "object" &&
        (trainingConfig["elyanModel"] as Record<string, unknown>)["nextAction"] === "run_shadow_evaluation",
      true,
    );
    assert.equal(
      trainingConfig["elyanProviderPlan"] &&
        typeof trainingConfig["elyanProviderPlan"] === "object" &&
        (trainingConfig["elyanProviderPlan"] as Record<string, unknown>)["routeReason"] === "shadow_eval_only",
      true,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("queueContinuousBrainTrainingJob rejects raw-signal training without approved corrections", async () => {
  const inserted: Array<{ table: string; values: Record<string, unknown> }> = [];
  const app = {
    db: new FakeDb(
      [
        [],
        [{ documents: 0, chunks: 0 }],
        [{ queued: 0, running: 0 }],
        [{ ready: 1, total: 1 }],
        [
          {
            safeEvents: 64,
            interactionEvents: 24,
            feedbackEvents: 12,
            runtimeEvents: 8,
            systemEvents: 4,
            routingSignals: 14,
            bridgeSignals: 10,
          },
        ],
        makeLearningQualityRow({
          thumbsUp: 9,
          thumbsDown: 1,
          regenerate: 1,
          toneSignals: 3,
          humorSignals: 1,
          brevitySignals: 2,
          helpfulnessSignals: 4,
          taskRoutingSignals: 2,
        }),
        [{ mobileDevices: 0, desktopDevices: 0, connectedDesktopDevices: 0 }],
        [],
        [{ totalChunks: 0, embeddedChunks: 0, lastIndexedAt: null }],
        [{ pending: 0 }],
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
            pairedAt: new Date("2030-01-03T00:00:00.000Z"),
            lastSeenAt: new Date("2030-01-03T00:00:00.000Z"),
            createdAt: new Date("2030-01-03T00:00:00.000Z"),
            updatedAt: new Date("2030-01-03T00:00:00.000Z"),
          },
        ],
        [],
        [],
        [],
        [],
        [{ freshSignals: 0, reconnectRecoveries: 0, handoffQualitySignals: 0 }],
        [],
        [],
      ],
      inserted,
    ),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_SYSTEM_PROMPT: "System prompt",
      ELYAN_USER_UNDERSTANDING_ENABLED: true,
      ELYAN_PERSONALIZATION_ENABLED: true,
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
  };

  const result = await queueContinuousBrainTrainingJob(app as never, {
    userId: "user-1",
    requestId: "req-no-approved",
  });

  assert.equal(result.created, false);
  assert.equal(result.job, null);
  assert.equal(result.reason, "approved_correction_dataset_required");
  assert.equal(inserted.some((entry) => entry.values["name"] === "Elyan continuous brain refresh"), false);
});

test("queueContinuousBrainTrainingJob blocks when quality signals are too weak", async () => {
  const inserted: Array<{ table: string; values: Record<string, unknown> }> = [];
  const app = {
    db: new FakeDb(
      [
        [],
        [{ documents: 0, chunks: 0 }],
        [{ queued: 0, running: 0 }],
        [{ ready: 0, total: 0 }],
        [
          {
            safeEvents: 12,
            interactionEvents: 6,
            feedbackEvents: 1,
            runtimeEvents: 2,
            systemEvents: 1,
            routingSignals: 0,
            bridgeSignals: 0,
          },
        ],
        makeLearningQualityRow({
          thumbsUp: 1,
          thumbsDown: 0,
          regenerate: 0,
          toneSignals: 0,
          humorSignals: 0,
          brevitySignals: 0,
          helpfulnessSignals: 1,
          taskRoutingSignals: 0,
        }),
        [{ mobileDevices: 0, desktopDevices: 0, connectedDesktopDevices: 0 }],
        [],
        [{ totalChunks: 0, embeddedChunks: 0, lastIndexedAt: null }],
        [{ pending: 0 }],
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
            pairedAt: new Date("2030-01-03T00:00:00.000Z"),
            lastSeenAt: new Date("2030-01-03T00:00:00.000Z"),
            createdAt: new Date("2030-01-03T00:00:00.000Z"),
            updatedAt: new Date("2030-01-03T00:00:00.000Z"),
          },
        ],
        [],
        [],
        [],
        [],
        [{ freshSignals: 0, reconnectRecoveries: 0, handoffQualitySignals: 0 }],
      ],
      inserted,
    ),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
      HOST: "0.0.0.0",
      PORT: 4000,
      ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
      ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
      ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
      ELYAN_SHARED_BRAIN_SYSTEM_PROMPT: "System prompt",
      ELYAN_USER_UNDERSTANDING_ENABLED: true,
      ELYAN_PERSONALIZATION_ENABLED: true,
      ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    },
  };

  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response("{}", { status: 200 });

  try {
    const result = await queueContinuousBrainTrainingJob(app as never, {
      userId: "user-1",
      requestId: "req-blocked",
    });

    assert.equal(result.created, false);
    assert.equal(result.job, null);
    assert.equal(result.reason, "quality_gate_low_signal");
    assert.equal(inserted.some((entry) => entry.values["name"] === "Elyan continuous brain refresh"), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("createModelArtifact fails closed when a ready artifact is missing integrity fields", async () => {
  await assert.rejects(
    async () =>
      createModelArtifact(
        {
          db: {} as never,
        } as never,
        {
          userId: "user-1",
          name: "Shared model",
          scope: "user",
          provider: "manual",
          baseModel: "llama3.2",
          adapterKind: "lora",
          status: "ready",
          metadata: {},
        },
      ),
    (error: unknown) => {
      assert.equal(
        typeof error === "object" && error !== null && "statusCode" in error
          ? (error as { statusCode?: unknown }).statusCode
          : null,
        400,
      );
      return true;
    },
  );
});
