import assert from "node:assert/strict";
import test from "node:test";
import {
  buildCognitiveContextPacket,
  cognitiveContextPacketSchema,
  renderCognitiveContextPacket,
} from "./cognitive-context.js";

test("cognitive context packet remains typed and JSON-only", () => {
  const packet = cognitiveContextPacketSchema.parse({
    version: "cognitive_context.v2",
    userId: "11111111-1111-4111-8111-111111111111",
    generatedAt: "2026-07-05T12:00:00.000Z",
    working: {
      sessionId: null,
      dialogueRevision: 2,
      memoryRevision: 8,
      goal: null,
      stage: null,
      openLoops: [],
      salience: {
        topics: [],
        entities: [],
        userIntent: null,
        assistantCommitment: null,
        emotionalTone: null,
        unresolved: false,
      },
      recentTools: [],
      conversation: { turnCount: 3, averageReplyChars: 120 },
    },
    semantic: [],
    episodic: [],
    uncertainty: {
      contestedFactCount: 0,
      contestedKeys: [],
      missingEvidence: ["no_durable_memory"],
      retrievalConfidence: 0,
    },
    budget: { maxChars: 4000, usedChars: 0, semanticLimit: 12, episodicLimit: 8 },
  });

  assert.deepEqual(JSON.parse(renderCognitiveContextPacket(packet)), packet);
});

test("social-turn context keeps semantic facts while skipping episodic and contested queries", async () => {
  let selectCalls = 0;
  const selectedRows = [
    [],
    [{
      id: "22222222-2222-4222-8222-222222222222",
      key: "preferred_tone",
      value: "warm_natural",
      confidence: 80,
      revision: 3,
      sourceKind: "learning_event",
      observedAt: new Date("2026-07-01T12:00:00.000Z"),
      validFrom: new Date("2026-07-01T12:00:00.000Z"),
    }],
  ];
  const db = {
    execute: async () => ({ rows: [] }),
    transaction: async (run: (tx: unknown) => Promise<unknown>) => run(db),
    select() {
      const rows = selectedRows[selectCalls++] ?? [];
      const builder = {
        from() { return builder; },
        where() { return builder; },
        orderBy() { return builder; },
        limit: async () => rows,
      };
      return builder;
    },
  };

  const packet = await buildCognitiveContextPacket(
    { db } as never,
    {
      userId: "11111111-1111-4111-8111-111111111111",
      includeEpisodes: false,
      includeContested: false,
      now: new Date("2026-07-27T12:00:00.000Z"),
    },
  );

  assert.equal(selectCalls, 2);
  assert.equal(packet.semantic[0]?.key, "preferred_tone");
  assert.deepEqual(packet.episodic, []);
  assert.equal(packet.uncertainty.contestedFactCount, 0);
});
