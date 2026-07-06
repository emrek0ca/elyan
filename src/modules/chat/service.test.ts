import assert from "node:assert/strict";
import test from "node:test";
import {
  buildChatDispatchDeliverySnapshot,
  buildChatTurnAdmissionLockKey,
  enrichChatMetadataForRequest,
  extractAttachmentCandidatesFromChatRows,
  getChatSessionDetail,
  listChatSessionMessages,
  listChatSessions,
  estimatePendingChatTokenDebit,
  resolveChatSessionTargetDeviceId,
  trimConversationForSharedBrain,
} from "./service.js";

test("buildChatTurnAdmissionLockKey normalizes same prompt for admission dedupe", () => {
  const first = buildChatTurnAdmissionLockKey({
    userId: "user-1",
    sessionId: "session-1",
    content: "  Selam   Zeynep  ",
  });
  const second = buildChatTurnAdmissionLockKey({
    userId: "user-1",
    sessionId: "session-1",
    content: "selam zeynep",
  });
  const otherSession = buildChatTurnAdmissionLockKey({
    userId: "user-1",
    sessionId: "session-2",
    content: "selam zeynep",
  });

  assert.equal(first, second);
  assert.notEqual(first, otherSession);
  assert.equal(
    buildChatTurnAdmissionLockKey({
      userId: "user-1",
      sessionId: "session-1",
      content: "   ",
    }),
    null,
  );
});

class FakeQuery<T> {
  private readonly result: T;
  private readonly onLimit?: (value: number | undefined) => void;

  constructor(result: T, onLimit?: (value: number | undefined) => void) {
    this.result = result;
    this.onLimit = onLimit;
  }

  from() {
    return this;
  }

  where() {
    return this;
  }

  orderBy() {
    return this;
  }

  limit(value?: number) {
    this.onLimit?.(value);
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
  readonly limitCalls: Array<number | undefined> = [];
  private readonly results: unknown[];

  constructor(results: unknown[]) {
    this.results = results;
  }

  select() {
    return new FakeQuery(this.results.shift() ?? [], (value) => {
      this.limitCalls.push(value);
    });
  }
}

function conditionUsesColumn(value: unknown, columnName: string, seen = new WeakSet<object>()): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  if (seen.has(value)) {
    return false;
  }
  seen.add(value);
  const record = value as Record<string, unknown>;
  if (record.name === columnName && typeof record.columnType === "string") {
    return true;
  }
  const queryChunks = record.queryChunks;
  if (Array.isArray(queryChunks)) {
    return queryChunks.some((chunk) => conditionUsesColumn(chunk, columnName, seen));
  }
  if (Array.isArray(value)) {
    return value.some((chunk) => conditionUsesColumn(chunk, columnName, seen));
  }
  return false;
}

class WorldSignalDb {
  readonly forbiddenFilterSeen: boolean[] = [];

  select() {
    const forbiddenFilterSeen = this.forbiddenFilterSeen;
    const row = {
      signalId: "health-1",
      source: "mobile",
      kind: "health",
      summary: "Enerji orta, stres yüksek.",
      confidenceBps: 860,
      facts: { energyLevel: "medium", stressLevel: "elevated" },
      privacy: { rawDataUploaded: false, precision: "summary", backendPlaintextAllowed: true },
      renderHints: {},
      visibility: "assistant_internal_by_default",
      createdAt: new Date("2030-01-01T12:00:00.000Z"),
    };
    return {
      from() {
        return {
          where(condition: unknown) {
            const hasForbiddenFilter =
              conditionUsesColumn(condition, "device_id") ||
              conditionUsesColumn(condition, "session_id");
            forbiddenFilterSeen.push(hasForbiddenFilter);
            return {
              orderBy() {
                return {
                  limit: async () => (hasForbiddenFilter ? [] : [row]),
                };
              },
            };
          },
        };
      },
    };
  }
}

test("trimConversationForSharedBrain keeps the latest fourteen non-system messages in order", () => {
  const conversation = Array.from({ length: 16 }, (_, index) => ({
    role: index % 2 == 0 ? "user" : "assistant",
    content: `message-${index + 1}`,
  })) as Array<{ role: "user" | "assistant"; content: string }>;

  const trimmed = trimConversationForSharedBrain(conversation);

  assert.equal(trimmed.length, 14);
  assert.deepEqual(
    trimmed.map((item) => item.content),
    [
      "message-3",
      "message-4",
      "message-5",
      "message-6",
      "message-7",
      "message-8",
      "message-9",
      "message-10",
      "message-11",
      "message-12",
      "message-13",
      "message-14",
      "message-15",
      "message-16",
    ],
  );
});

test("trimConversationForSharedBrain respects the token budget while preserving recency order", () => {
  const conversation = [
    {
      role: "user",
      content: "a".repeat(1500),
    },
    {
      role: "assistant",
      content: "b".repeat(1500),
    },
    {
      role: "user",
      content: "c".repeat(20),
    },
  ] as Array<{ role: "user" | "assistant"; content: string }>;

  const trimmed = trimConversationForSharedBrain(conversation, {
    maxTokens: 300,
  });

  assert.deepEqual(
    trimmed.map((item) => item.content.length),
    [20],
  );
});

test("trimConversationForSharedBrain bounds a single oversized recent message", () => {
  const trimmed = trimConversationForSharedBrain(
    [
      {
        role: "assistant",
        content: "x".repeat(8_000),
      },
    ],
    {
      maxTokens: 300,
    },
  );

  assert.equal(trimmed.length, 1);
  assert.equal(trimmed[0]?.content.length, 1_200);
});

test("resolveChatSessionTargetDeviceId ignores a selected desktop for shared-brain chat", () => {
  assert.equal(
    resolveChatSessionTargetDeviceId(
      {
        route: "server_brain",
      },
      "desktop-1",
    ),
    undefined,
  );
});

test("resolveChatSessionTargetDeviceId preserves the selected desktop for desktop chat tasks", () => {
  assert.equal(
    resolveChatSessionTargetDeviceId(
      {
        route: "desktop_runtime",
      },
      "desktop-1",
    ),
    "desktop-1",
  );
});

test("enrichChatMetadataForRequest keeps fresh world signals user-scoped for server-brain chat", async () => {
  const db = new WorldSignalDb();
  const metadata = await enrichChatMetadataForRequest(
    { db } as never,
    {
      userId: "user-1",
      sessionId: "session-1",
      targetDeviceId: "shared-brain-device",
      metadata: { smoke: true },
    },
  );

  const chatContext = metadata.chatContext as Record<string, unknown>;
  const digest = chatContext.lastDerivedContextDigest as Record<string, unknown>;
  const worldSignals = digest.worldSignals as Array<Record<string, unknown>>;

  assert.deepEqual(db.forbiddenFilterSeen, [false]);
  assert.equal(worldSignals.length, 1);
  assert.equal(worldSignals[0]?.kind, "health");
  assert.match(String(worldSignals[0]?.summary ?? ""), /Enerji orta/);
  assert.deepEqual(worldSignals[0]?.facts, {
    energyLevel: "medium",
    stressLevel: "elevated",
  });
  assert.deepEqual(worldSignals[0]?.privacy, {
    rawDataUploaded: false,
    precision: "summary",
    backendPlaintextAllowed: true,
  });
});

test("buildChatDispatchDeliverySnapshot preserves desktop ack and lease truth", () => {
  const delivery = buildChatDispatchDeliverySnapshot({
    task: {
      id: "task-1",
      targetDeviceId: "desktop-1",
      deliveryState: "dispatched",
      deliveryAttemptCount: 2,
      dispatchLeaseId: "lease-1",
      dispatchLeaseExpiresAt: "2030-01-01T12:00:30.000Z",
      dispatchAckAt: null,
      lastAckAt: null,
      lastDispatchAttemptAt: "2030-01-01T12:00:00.000Z",
    },
    requestedTargetDeviceId: "desktop-1",
    routeDecision: {
      route: "desktop_runtime",
      taskRoute: {
        needsDesktop: true,
        operationalRoute: "desktop_runtime",
      },
    },
  });

  assert.equal(delivery.route, "desktop_runtime");
  assert.equal(delivery.presentation, "chat");
  assert.equal(delivery.targetDeviceId, "desktop-1");
  assert.equal(delivery.requestedTargetDeviceId, "desktop-1");
  assert.equal(delivery.requiresDesktopAck, true);
  assert.equal(delivery.deliveryState, "dispatched");
  assert.equal(delivery.dispatchLeaseId, "lease-1");
  assert.equal(delivery.lastAckAt, null);
});

test("estimatePendingChatTokenDebit gives short queued server-brain chat an immediate token debit", () => {
  assert.equal(
    estimatePendingChatTokenDebit({
      route: "server_brain",
      reused: false,
      taskStatus: "queued",
      content: "Selam",
      workload: "mobile_chat_fast",
      brainProfile: {
        tier: "premium",
        reasoningMultiplier: 5,
        retrievalFanout: 5,
        memoryFanout: 6,
        maxTokenScale: 1.25,
      },
    }),
    1,
  );
});

test("estimatePendingChatTokenDebit does not double-count reused, terminal, or desktop-routed work", () => {
  const base = {
    route: "server_brain",
    reused: false,
    taskStatus: "queued",
    content: "Selam",
    workload: "mobile_chat_fast" as const,
  };

  assert.equal(estimatePendingChatTokenDebit({ ...base, reused: true }), 0);
  assert.equal(estimatePendingChatTokenDebit({ ...base, taskStatus: "completed" }), 0);
  assert.equal(estimatePendingChatTokenDebit({ ...base, route: "desktop_runtime" }), 0);
});

test("estimatePendingChatTokenDebit supports the document analysis workload profile", () => {
  const debit = estimatePendingChatTokenDebit({
    route: "server_brain",
    reused: false,
    taskStatus: "queued",
    content: "Bu belgeyi detaylı incele",
    workload: "document_analysis",
    brainProfile: {
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 5,
      memoryFanout: 6,
      maxTokenScale: 1.25,
    },
  });

  assert.ok(debit >= 1);
});

test("extractAttachmentCandidatesFromChatRows keeps recent unique user attachment contexts for follow-up recovery", () => {
  const rows = [
    {
      id: "message-1",
      role: "user",
      content: "İlk belge",
      createdAt: new Date("2030-01-01T12:00:00.000Z"),
      metadata: {
        attachments: [
          {
            documentId: "doc-1",
            fileName: "ilk.pdf",
            compactDocument: {
              documentId: "doc-1",
              fileName: "ilk.pdf",
            },
            document_analysis: {
              documentId: "doc-1",
              extractedText: "İlk belge içeriği",
            },
          },
        ],
      },
    },
    {
      id: "message-2",
      role: "assistant",
      content: "Tamam",
      createdAt: new Date("2030-01-01T12:01:00.000Z"),
      metadata: {},
    },
    {
      id: "message-3",
      role: "user",
      content: "Sadece takip mesajı",
      createdAt: new Date("2030-01-01T12:02:00.000Z"),
      metadata: {},
    },
    {
      id: "message-4",
      role: "user",
      content: "Son belge",
      createdAt: new Date("2030-01-01T12:03:00.000Z"),
      metadata: {
        attachments: [
          {
            documentId: "doc-2",
            fileName: "son.pdf",
            compactDocument: {
              documentId: "doc-2",
              fileName: "son.pdf",
            },
            document_analysis: {
              documentId: "doc-2",
              extractedText: "Son belge içeriği",
            },
          },
        ],
      },
    },
    {
      id: "message-5",
      role: "user",
      content: "Aynı belge tekrar",
      createdAt: new Date("2030-01-01T12:04:00.000Z"),
      metadata: {
        attachments: [
          {
            documentId: "doc-2",
            fileName: "son.pdf",
            compactDocument: {
              documentId: "doc-2",
              fileName: "son.pdf",
            },
            document_analysis: {
              documentId: "doc-2",
              extractedText: "Son belge içeriği",
            },
          },
        ],
      },
    },
  ];

  const candidates = extractAttachmentCandidatesFromChatRows(rows);

  assert.equal(candidates.length, 2);
  assert.equal(candidates[0]?.messageId, "message-5");
  assert.equal(candidates[1]?.messageId, "message-1");
});

test("listChatSessions returns lightweight rows with pagination metadata", async () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const app = {
    db: new FakeDb([
      [
        {
          id: "session-2",
          userId: "user-1",
          title: "Yeni görev",
          metadata: {
            chatHistory: {
              preview: "Belge özeti",
            },
          },
          status: "active",
          targetDeviceId: "shared-brain-device",
          source: "mobile",
          createdAt: now,
          updatedAt: now,
          lastMessageAt: now,
        },
        {
          id: "session-1",
          userId: "user-1",
          title: "Toplantı notları",
          metadata: {
            preview: "Toplantı notları",
          },
          status: "active",
          targetDeviceId: "shared-brain-device",
          source: "mobile",
          createdAt: now,
          updatedAt: now,
          lastMessageAt: now,
        },
      ],
    ]),
  };

  const page = await listChatSessions(app as never, {
    userId: "user-1",
    limit: 1,
  });

  assert.equal(page.sessions.length, 1);
  assert.equal(page.sessions[0]?.title, "Belge özeti");
  assert.equal(page.sessions[0]?.preview, "Belge özeti");
  assert.equal(page.hasMore, true);
  assert.ok(page.nextCursor);
});

test("listChatSessionMessages returns the latest page first and keeps chronological order", async () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const app = {
    db: new FakeDb([
      [
        {
          id: "session-1",
          userId: "user-1",
          title: "Selam",
          metadata: {},
          status: "active",
          targetDeviceId: "shared-brain-device",
          source: "mobile",
          createdAt: now,
          updatedAt: now,
          lastMessageAt: now,
        },
      ],
      [
        {
          id: "message-2",
          sessionId: "session-1",
          userId: "user-1",
          role: "assistant",
          content: "Merhaba",
          createdAt: new Date("2030-01-01T12:01:00.000Z"),
          updatedAt: new Date("2030-01-01T12:01:00.000Z"),
        },
        {
          id: "message-1",
          sessionId: "session-1",
          userId: "user-1",
          role: "user",
          content: "Selam",
          createdAt: now,
          updatedAt: now,
        },
      ],
    ]),
  };

  const page = await listChatSessionMessages(app as never, {
    userId: "user-1",
    sessionId: "session-1",
    limit: 1,
  });

  assert.equal(page.session.id, "session-1");
  assert.equal(page.messages.length, 1);
  assert.equal(Object.hasOwn(page.messages[0] ?? {}, "content"), false);
  const firstBlock = page.messages[0]?.blocks?.[0];
  assert.equal(firstBlock?.type, "text");
  assert.equal(firstBlock?.markdown, "Merhaba");
  assert.equal(firstBlock?.visibility, "user_visible");
  assert.ok(firstBlock?.stableBlockId);
  assert.ok(firstBlock?.cacheDigest);
  assert.equal(page.hasMore, true);
  assert.ok(page.nextCursor);
});

test("listChatSessionMessages defaults to latest 30 messages on first page and older 10 with cursor", async () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const db = new FakeDb([
    [
      {
        id: "session-1",
        userId: "user-1",
        title: "Selam",
        metadata: {},
        status: "active",
        targetDeviceId: "shared-brain-device",
        source: "mobile",
        createdAt: now,
        updatedAt: now,
        lastMessageAt: now,
      },
    ],
    [],
    [
      {
        id: "session-1",
        userId: "user-1",
        title: "Selam",
        metadata: {},
        status: "active",
        targetDeviceId: "shared-brain-device",
        source: "mobile",
        createdAt: now,
        updatedAt: now,
        lastMessageAt: now,
      },
    ],
    [],
  ]);
  const app = { db };

  await listChatSessionMessages(app as never, {
    userId: "user-1",
    sessionId: "session-1",
  });
  await listChatSessionMessages(app as never, {
    userId: "user-1",
    sessionId: "session-1",
    cursor: Buffer.from(
      JSON.stringify({
        timestamp: now.toISOString(),
        id: "message-30",
      }),
      "utf8",
    ).toString("base64url"),
  });

  assert.deepEqual(db.limitCalls, [1, 31, 1, 11]);
});

test("getChatSessionDetail returns the latest window instead of eager full history", async () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const app = {
    db: new FakeDb([
      [
        {
          id: "session-1",
          userId: "user-1",
          title: "Selam",
          metadata: {},
          status: "active",
          targetDeviceId: "shared-brain-device",
          source: "mobile",
          createdAt: now,
          updatedAt: now,
          lastMessageAt: now,
        },
      ],
      [
        {
          id: "message-3",
          sessionId: "session-1",
          userId: "user-1",
          role: "assistant",
          content: "Üç",
          createdAt: new Date("2030-01-01T12:03:00.000Z"),
          updatedAt: new Date("2030-01-01T12:03:00.000Z"),
        },
        {
          id: "message-2",
          sessionId: "session-1",
          userId: "user-1",
          role: "assistant",
          content: "İki",
          createdAt: new Date("2030-01-01T12:02:00.000Z"),
          updatedAt: new Date("2030-01-01T12:02:00.000Z"),
        },
        {
          id: "message-1",
          sessionId: "session-1",
          userId: "user-1",
          role: "user",
          content: "Bir",
          createdAt: new Date("2030-01-01T12:01:00.000Z"),
          updatedAt: new Date("2030-01-01T12:01:00.000Z"),
        },
      ],
    ]),
  };

  const detail = await getChatSessionDetail(app as never, "user-1", "session-1");

  assert.equal(detail.session.id, "session-1");
  assert.equal(detail.messages[0]?.content, "Bir");
  assert.equal(Object.hasOwn(detail.messages[1] ?? {}, "content"), false);
  assert.equal(detail.messages[1]?.blocks?.[0]?.type, "text");
  assert.equal(detail.messages[1]?.blocks?.[0]?.markdown, "İki");
  assert.equal(Object.hasOwn(detail.messages[2] ?? {}, "content"), false);
  assert.equal(detail.messages[2]?.blocks?.[0]?.type, "text");
  assert.equal(detail.messages[2]?.blocks?.[0]?.markdown, "Üç");
  assert.equal(detail.hasMore, false);
  assert.equal(detail.nextCursor, null);
});
