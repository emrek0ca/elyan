import assert from "node:assert/strict";
import test from "node:test";
import { buildMemoryProfileSnapshot, formatMemoryProfilePromptBlock } from "./memory-profile.js";

test("buildMemoryProfileSnapshot summarizes stable identity and preference memory safely", () => {
  const snapshot = buildMemoryProfileSnapshot([
    {
      id: "1",
      type: "semantic",
      key: "name",
      value: "Osman Emre Koca",
      confidence: 0.96,
      scope: "user",
      source: "semantic_memory",
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-01T00:00:00.000Z"),
      importanceScore: 90,
      isPinned: true,
    },
    {
      id: "2",
      type: "style",
      key: "response_style_preference",
      value: "balanced",
      confidence: 0.92,
      scope: "user",
      source: "interaction",
      createdAt: new Date("2030-01-02T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-02T00:00:00.000Z"),
      importanceScore: 82,
      isPinned: false,
    },
    {
      id: "3",
      type: "reflective",
      key: "negative_feedback",
      value: "avoid leaking private details",
      confidence: 0.88,
      scope: "user",
      source: "feedback",
      createdAt: new Date("2030-01-03T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-03T00:00:00.000Z"),
      importanceScore: 74,
      isPinned: false,
    },
  ]);

  assert.equal(snapshot.identityFacts[0]?.value, "Osman Emre Koca");
  assert.equal(snapshot.preferenceFacts[0]?.value, "balanced");
  assert.ok(snapshot.safetyNotes.some((item) => item.includes("avoid leaking private details")));
  assert.ok(snapshot.summary?.includes("Kullanıcının adı Osman Emre Koca"));
  assert.ok(snapshot.summary?.includes("Cevap stili: Dengeli"));
});

test("buildMemoryProfileSnapshot renders Turkish language preferences naturally", () => {
  const snapshot = buildMemoryProfileSnapshot([
    {
      id: "1",
      type: "preference",
      key: "preferred_language",
      value: "Turkish",
      confidence: 0.94,
      scope: "user",
      source: "interaction",
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-01T00:00:00.000Z"),
      importanceScore: 84,
      isPinned: true,
    },
    {
      id: "2",
      type: "style",
      key: "response_style_preference",
      value: "warm",
      confidence: 0.91,
      scope: "user",
      source: "interaction",
      createdAt: new Date("2030-01-02T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-02T00:00:00.000Z"),
      importanceScore: 78,
      isPinned: false,
    },
  ]);

  assert.ok(snapshot.summary?.includes("Tercih edilen dil Türkçe"));
  assert.ok(snapshot.summary?.includes("Cevap stili: Sıcak"));
});

test("buildMemoryProfileSnapshot renders Turkic family language preferences naturally", () => {
  const snapshot = buildMemoryProfileSnapshot([
    {
      id: "1",
      type: "preference",
      key: "preferred_language",
      value: "Turkic",
      confidence: 0.94,
      scope: "user",
      source: "interaction",
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-01T00:00:00.000Z"),
      importanceScore: 84,
      isPinned: true,
    },
  ]);

  assert.ok(snapshot.summary?.includes("Tercih edilen dil Türk dilleri"));
});

test("buildMemoryProfileSnapshot keeps only the strongest fact per key and records compaction", () => {
  const snapshot = buildMemoryProfileSnapshot([
    {
      id: "1",
      type: "semantic",
      key: "name",
      value: "Osman Emre Koca",
      confidence: 0.84,
      scope: "user",
      source: "semantic_memory",
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-01T00:00:00.000Z"),
      importanceScore: 70,
      isPinned: false,
    },
    {
      id: "2",
      type: "semantic",
      key: "name",
      value: "Osman Emre Koca",
      confidence: 0.98,
      scope: "user",
      source: "semantic_memory",
      createdAt: new Date("2030-01-02T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-02T00:00:00.000Z"),
      importanceScore: 90,
      isPinned: true,
    },
    {
      id: "3",
      type: "semantic",
      key: "preferred_tone",
      value: "warm",
      confidence: 0.91,
      scope: "user",
      source: "interaction",
      createdAt: new Date("2030-01-03T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-03T00:00:00.000Z"),
      importanceScore: 80,
      isPinned: false,
    },
  ]);

  assert.equal(snapshot.identityFacts.length, 1);
  assert.equal(snapshot.identityFacts[0]?.confidence, 0.98);
  assert.equal(snapshot.compactedCount > 0, true);
});

test("buildMemoryProfileSnapshot prefers verified fresh facts over stale contested ones", () => {
  const snapshot = buildMemoryProfileSnapshot([
    {
      id: "1",
      type: "semantic",
      key: "project",
      value: "mobile-elyan",
      confidence: 0.82,
      scope: "project",
      source: "semantic_memory",
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      staleness: "stale",
      conflictStatus: "active",
      importanceScore: 60,
      isPinned: false,
    },
    {
      id: "2",
      type: "semantic",
      key: "project",
      value: "mobile-elyan",
      confidence: 0.88,
      scope: "project",
      source: "semantic_memory",
      createdAt: new Date("2030-01-02T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-03T00:00:00.000Z"),
      importanceScore: 78,
      isPinned: true,
    },
    {
      id: "3",
      type: "semantic",
      key: "project",
      value: "mobile-elyan",
      confidence: 0.95,
      scope: "project",
      source: "semantic_memory",
      createdAt: new Date("2030-01-03T00:00:00.000Z"),
      staleness: "contested",
      conflictStatus: "contested",
      importanceScore: 92,
      isPinned: false,
    },
  ]);

  assert.equal(snapshot.projectFacts.length, 1);
  assert.equal(snapshot.projectFacts[0]?.value, "mobile-elyan");
  assert.equal(snapshot.projectFacts[0]?.confidence, 0.88);
});

test("buildMemoryProfileSnapshot collapses near duplicate values for the same key", () => {
  const snapshot = buildMemoryProfileSnapshot([
    {
      id: "1",
      type: "style",
      key: "answer_length",
      value: "balanced",
      confidence: 0.9,
      scope: "user",
      source: "interaction",
      createdAt: new Date("2030-01-01T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-01T00:00:00.000Z"),
      importanceScore: 72,
      isPinned: false,
    },
    {
      id: "2",
      type: "style",
      key: "answer_length",
      value: "balnced",
      confidence: 0.89,
      scope: "user",
      source: "interaction",
      createdAt: new Date("2030-01-02T00:00:00.000Z"),
      staleness: "fresh",
      conflictStatus: "active",
      lastVerifiedAt: new Date("2030-01-02T00:00:00.000Z"),
      importanceScore: 70,
      isPinned: false,
    },
  ]);

  assert.equal(snapshot.preferenceFacts.length, 1);
  assert.equal(snapshot.preferenceFacts[0]?.value, "balanced");
});

test("formatMemoryProfilePromptBlock renders a compact prompt-safe summary", () => {
  const block = formatMemoryProfilePromptBlock({
    summary: "Hatırlanan çekirdek: kimlik=Ad: Osman Emre Koca | tercih=Cevap stili: balanced",
    identityFacts: [
      {
        key: "name",
        label: "Ad",
        value: "Osman Emre Koca",
        confidence: 0.96,
        source: "semantic_memory",
        staleness: "fresh",
        updatedAt: "2030-01-01T00:00:00.000Z",
      },
    ],
    preferenceFacts: [],
    projectFacts: [],
    derivedFacts: [],
    recentEpisodes: [],
    safetyNotes: ["privacy boundary: keep private local data local"],
    memoryCount: 1,
    compactedCount: 0,
    lastUpdatedAt: "2030-01-01T00:00:00.000Z",
  });

  assert.ok(block?.includes("User memory profile:"));
  assert.ok(block?.includes("Kullanıcının adı Osman Emre Koca'dır."));
  assert.ok(block?.includes("Privacy boundary"));
});
