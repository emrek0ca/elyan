import assert from "node:assert/strict";
import test from "node:test";
import {
  assertSafeWorldSignalPayload,
  buildWorldSignalLogContext,
  ingestWorldSignals,
  shapeMobileBootstrapBrain,
} from "./service.js";

test("shapeMobileBootstrapBrain preserves the full memory snapshot", () => {
  const shaped = shapeMobileBootstrapBrain({
    chat: {
      configuredBaseModel: "groq",
      resolvedBaseModel: "groq",
      resolvedBaseModelSource: "provider",
      availableModels: [],
      activeSharedModel: null,
      activeUserModel: null,
      dispatchPath: "/v1/tasks",
      brainProfilePath: "/v1/brain/profile",
      realtimePath: "/v1/realtime/stream",
      messagesPath: "/v1/chat/messages",
      inferenceReady: true,
      mobileDocumentExportReady: true,
      isChatUsable: true,
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
    quota: null,
    bridge: null,
    quantum: null,
    retrieval: {
      readyDocuments: 0,
      readyChunks: 0,
      mode: "hybrid",
      embeddingCoverage: 0,
      pendingIndexJobs: 0,
      lastIndexedAt: null,
      memorySources: [],
      memoryIndexCoverage: 0,
      memorySourceCoverage: 0,
      memoryRecallMode: "lexical_memory_fallback",
    },
    learning: {
      userUnderstandingEnabled: true,
      personalizationEnabled: true,
      safeLearningEvents: 0,
      signalSummary: null,
      responseStylePreference: null,
      qualitySignals: null,
      humorMode: null,
      recentFeedbackSummary: null,
    },
    training: {
      signalSummary: {
        interactionEvents: 0,
        feedbackEvents: 0,
        runtimeEvents: 0,
        systemEvents: 0,
        routingSignals: 0,
        bridgeSignals: 0,
      },
      pipeline: {
        runtimeReady: true,
        bridgeLearning: {
          routingSignals: 0,
          bridgeSignals: 0,
          mobileDevices: 0,
          desktopDevices: 0,
          connectedDesktopDevices: 0,
        },
        personaTarget: "warm_professional_balanced",
        mobileChatFocus: true,
      },
      brainLatency: null,
      qualitySignalSummary: {
        toneSignals: 0,
        humorSignals: 0,
        brevitySignals: 0,
        helpfulnessSignals: 0,
        taskRoutingSignals: 0,
      },
      signalFreshness: null,
    },
    memory: {
      workingMemoryBudget: {
        maxConversationMessages: 6,
        maxPromptTokens: 900,
        maxMemoryHints: 8,
      },
      userMemoryProfile: {
        summary: "Kullanıcı adı Emre. Kısa, samimi yanıt seviyor.",
        identityFacts: [
          {
            key: "name",
            label: "Ad",
            value: "Emre",
            confidence: 0.95,
            source: "interaction",
            staleness: "fresh",
            updatedAt: "2030-01-01T10:00:00.000Z",
          },
        ],
        preferenceFacts: [
          {
            key: "response_style_preference",
            label: "Cevap stili",
            value: "kısa ve sıcak",
            confidence: 0.9,
            source: "feedback",
            staleness: "fresh",
            updatedAt: "2030-01-01T10:01:00.000Z",
          },
        ],
        projectFacts: [],
        recentEpisodes: [],
        safetyNotes: [],
        memoryCount: 2,
        compactedCount: 1,
        lastUpdatedAt: "2030-01-01T10:02:00.000Z",
      },
      compaction: {
        compactedCount: 1,
        activeSnapshotCount: 2,
        staleCount: 0,
        softDeletedCount: 0,
        contestedCount: 0,
        retentionWindows: {
          factsDays: 365,
          episodesDays: 120,
        },
        lastCompactedAt: "2030-01-01T10:02:00.000Z",
      },
      recallReady: true,
      activeSemanticCount: 1,
      recentEpisodeCount: 1,
      episodicMemoryCount: 1,
      semanticMemoryCount: 1,
      selfModelMemoryCount: 0,
      reflectiveMemoryCount: 0,
      pinnedMemoryCount: 0,
      softDeletedCount: 0,
      staleMemoryCount: 0,
      contestedMemoryCount: 0,
      recallPenaltySummary: {
        stalePenaltyActiveCount: 0,
        contestedPenaltyActiveCount: 0,
        lastMemoryIndexAt: "2030-01-01T10:02:00.000Z",
      },
      lastConsolidatedAt: "2030-01-01T10:01:00.000Z",
      lastReconsolidatedAt: "2030-01-01T10:02:00.000Z",
      lastSelfModelUpdatedAt: "2030-01-01T10:00:00.000Z",
    },
    metacognition: {
      selfModelReady: false,
      memoryAwareChatReady: true,
      contradictionGuardReady: true,
      memoryConflictGuardReady: true,
      reflectiveMemoryReady: false,
      memoryControlReady: true,
      lastSelfCheckAt: null,
    },
  } as never);

  assert.equal(
    shaped.memory.userMemoryProfile.summary,
    "Kullanıcı adı Emre. Kısa, samimi yanıt seviyor.",
  );
  assert.equal(shaped.memory.userMemoryProfile.identityFacts[0]?.value, "Emre");
  assert.equal(shaped.memoryAwareChatReady, true);
  assert.equal(shaped.chat.mobileDocumentExportReady, true);
  assert.equal(shaped.skills.enabled, true);
  assert.equal(shaped.skills.items[0]?.slashCommand, "/özetle");
});

test("assertSafeWorldSignalPayload rejects raw health samples", () => {
  assert.throws(
    () =>
      assertSafeWorldSignalPayload({
        schemaVersion: 1,
        clientRequestId: "req_1",
        deviceId: "mobile-device",
        signals: [
          {
            signalId: "sig_1",
            source: "mobile",
            kind: "health",
            summary: "derived",
            confidence: 0.8,
            facts: { stepCount: 4912 },
            privacy: { rawDataUploaded: false },
            createdAt: "2030-01-01T00:00:00.000Z",
          },
        ],
      }),
    /raw health/i,
  );
});

test("assertSafeWorldSignalPayload rejects precise location payloads", () => {
  assert.throws(
    () =>
      assertSafeWorldSignalPayload({
        schemaVersion: 1,
        clientRequestId: "req_1",
        deviceId: "mobile-device",
        signals: [
          {
            signalId: "sig_1",
            source: "mobile",
            kind: "location",
            summary: "derived",
            confidence: 0.8,
            facts: { latitude: 41.0082, longitude: 28.9784 },
            privacy: { rawDataUploaded: false },
            createdAt: "2030-01-01T00:00:00.000Z",
          },
        ],
      }),
    /Precise coordinates/i,
  );
});

test("assertSafeWorldSignalPayload rejects raw calendar fields and local paths", () => {
  assert.throws(
    () =>
      assertSafeWorldSignalPayload({
        schemaVersion: 1,
        clientRequestId: "req_1",
        deviceId: "mobile-device",
        signals: [
          {
            signalId: "sig_1",
            source: "mobile",
            kind: "calendar",
            summary: "/Users/emre/private.txt",
            confidence: 0.8,
            facts: { attendees: ["a@example.com"] },
            privacy: { rawDataUploaded: false },
            createdAt: "2030-01-01T00:00:00.000Z",
          },
        ],
      }),
    /(calendar|Local file paths)/i,
  );
});

test("ingestWorldSignals rejects foreign device ownership", async () => {
  const fakeDb = createIngestDb({ device: null, session: null });
  await assert.rejects(
    () =>
      ingestWorldSignals(
        {
          db: fakeDb,
          log: { info() {} },
        } as never,
        {
          userId: "user-1",
          externalDeviceId: "foreign-device",
          body: validWorldSignalBody(),
        },
      ),
    /device scope is not valid/i,
  );
});

test("ingestWorldSignals rejects foreign session ownership", async () => {
  const fakeDb = createIngestDb({
    device: { id: "device-1", isActive: true },
    session: null,
  });
  const body = validWorldSignalBody();
  body.sessionId = "11111111-1111-4111-8111-111111111111";
  await assert.rejects(
    () =>
      ingestWorldSignals(
        {
          db: fakeDb,
          log: { info() {} },
        } as never,
        {
          userId: "user-1",
          externalDeviceId: "device-ext",
          body,
        },
      ),
    /session scope is not valid/i,
  );
});

test("buildWorldSignalLogContext never includes raw summaries or transcripts", () => {
  const context = buildWorldSignalLogContext({
    accepted: false,
    reasonCode: "raw_payload_blocked",
    userId: "user-1",
    deviceId: "device-1",
    payloadBytes: 420,
    signals: [
      {
        kind: "speech",
        createdAt: "2030-01-01T00:00:00.000Z",
      },
    ],
  });

  assert.equal("summary" in context, false);
  assert.equal("transcript" in context, false);
  assert.deepEqual(context.kinds, ["speech"]);
});

function validWorldSignalBody() {
  return {
    schemaVersion: 1 as const,
    clientRequestId: "req_1",
    deviceId: "device-ext",
    sessionId: undefined as string | undefined,
    signals: [
      {
        signalId: "sig_1",
        source: "mobile" as const,
        kind: "device" as const,
        summary: "Device summary",
        confidence: 0.9,
        facts: { batteryBand: "normal" },
        privacy: { rawDataUploaded: false, precision: "summary" },
        createdAt: "2030-01-01T00:00:00.000Z",
      },
    ],
  };
}

function createIngestDb(input: {
  device: { id: string; isActive: boolean } | null;
  session: { id: string } | null;
}) {
  let selectCall = 0;
  return {
    select() {
      return {
        from() {
          return {
            where() {
              return {
                limit() {
                  selectCall += 1;
                  if (selectCall === 1) {
                    return Promise.resolve(input.device ? [input.device] : []);
                  }
                  return Promise.resolve(input.session ? [input.session] : []);
                },
              };
            },
          };
        },
      };
    },
    insert() {
      return {
        values() {
          return {
            onConflictDoNothing() {
              return Promise.resolve();
            },
          };
        },
      };
    },
  };
}
