import assert from "node:assert/strict";
import test from "node:test";
import {
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
