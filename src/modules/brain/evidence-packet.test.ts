import assert from "node:assert/strict";
import test from "node:test";
import {
  buildEvidencePacket,
  memoryHitsToEvidencePackets,
} from "./evidence-packet.js";

test("evidence packet excludes contested, stale and cross-user candidates", () => {
  const packet = buildEvidencePacket({
    userId: "user-a",
    namespace: "semantic_memory",
    query: "tercih",
    candidates: [
      {
        id: "active",
        content: "Kullanıcı kısa yanıtları tercih ediyor.",
        confidence: 0.95,
        score: 0.9,
        lifecycle: "active",
        scope: "user",
        ownerUserId: "user-a",
      },
      {
        id: "contested",
        content: "Çelişkili bilgi.",
        lifecycle: "contested",
        ownerUserId: "user-a",
      },
      {
        id: "other-user",
        content: "Başka kullanıcı bilgisi.",
        lifecycle: "active",
        scope: "user",
        ownerUserId: "user-b",
      },
    ],
  });

  assert.deepEqual(packet.entries.map((entry) => entry.sourceId), ["active"]);
  assert.equal(packet.contract, "elyan.evidence_packet.v1");
  assert.equal(packet.namespace, "semantic_memory");
});

test("memory evidence packets remain namespace-bounded and provenance-bearing", () => {
  const packets = memoryHitsToEvidencePackets({
    userId: "user-a",
    query: "hedef",
    memoryRevision: 7,
    hits: [
      {
        id: "fact-1",
        memorySource: "semantic_memory",
        memoryType: "preference",
        title: "Yanıt stili",
        content: "Kısa ve net yanıt.",
        confidence: 90,
        staleness: "fresh",
        importanceScore: 80,
        isPinned: true,
        conflictStatus: "active",
        lifecycleStatus: "active",
        scope: "user",
        score: 0.8,
        lastVerifiedAt: "2026-08-20T00:00:00.000Z",
        deletedAt: null,
        deletedReason: null,
        updatedAt: "2026-08-20T00:00:00.000Z",
        metadata: { sourceId: "fact-1" },
      },
    ],
  });

  assert.equal(packets.length, 1);
  assert.equal(packets[0]?.namespace, "semantic_memory");
  assert.equal(packets[0]?.memoryRevision, 7);
  assert.equal(packets[0]?.entries[0]?.sourceId, "fact-1");
});
