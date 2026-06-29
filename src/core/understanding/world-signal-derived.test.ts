import assert from "node:assert/strict";
import test from "node:test";
import {
  buildDerivedHintBuckets,
  deriveLearningSignalsFromWorldSignals,
  toDerivedSignalInput,
} from "./world-signal-derived.js";

test("deriveLearningSignalsFromWorldSignals creates safe derived traits without raw measurements", () => {
  const derived = deriveLearningSignalsFromWorldSignals([
    toDerivedSignalInput({
      signalId: "health-1",
      kind: "health",
      summary: "Nabız 92 bpm, enerji düşük",
      confidence: 0.92,
      facts: {
        readiness: 0.32,
        fatigue: "yüksek",
      },
      privacy: {
        backendPlaintextAllowed: false,
      },
      createdAt: new Date("2030-01-01T10:00:00.000Z"),
    }),
    toDerivedSignalInput({
      signalId: "calendar-1",
      kind: "calendar",
      summary: "Bugün çok toplantı var",
      confidence: 0.88,
      facts: {
        freeMinutesToday: 30,
        longestFreeBlockMinutes: 25,
      },
      privacy: {
        backendPlaintextAllowed: true,
      },
      createdAt: new Date("2030-01-01T10:00:00.000Z"),
    }),
  ]);

  const energy = derived.find((item) => item.key === "energy_rhythm");
  const schedule = derived.find((item) => item.key === "schedule_pressure_pattern");

  assert.ok(energy);
  assert.ok(schedule);
  assert.doesNotMatch(energy?.value ?? "", /92|bpm/i);
  assert.doesNotMatch(schedule?.value ?? "", /title|attendee|meeting link/i);
});

test("buildDerivedHintBuckets suppresses irrelevant world-signal hints for greetings", () => {
  const hints = buildDerivedHintBuckets({
    requestText: "Merhaba",
    memory: [
      {
        key: "energy_rhythm",
        value: "low energy window; prefer shorter, lower-friction steps",
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "situational",
        },
        staleness: "fresh",
      },
      {
        key: "common_city",
        value: "Istanbul",
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "environmental",
        },
        staleness: "fresh",
      },
    ],
  });

  assert.deepEqual(hints.situationalHints, []);
  assert.deepEqual(hints.environmentHints, []);
});

test("buildDerivedHintBuckets keeps behavioral and environmental hints gated by request relevance", () => {
  const genericHints = buildDerivedHintBuckets({
    requestText: "Bana kısa bir şiir yaz.",
    memory: [
      {
        key: "preferred_planning_granularity",
        value: "prefers compact time-boxed steps on busy days",
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "behavioral",
        },
        staleness: "fresh",
      },
      {
        key: "common_city",
        value: "Istanbul",
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "environmental",
        },
        staleness: "fresh",
      },
    ],
  });

  assert.deepEqual(genericHints.behavioralHints, []);
  assert.deepEqual(genericHints.environmentHints, []);

  const planningHints = buildDerivedHintBuckets({
    requestText: "Bugünkü çalışma planımı çıkar.",
    memory: [
      {
        key: "preferred_planning_granularity",
        value: "prefers compact time-boxed steps on busy days",
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "behavioral",
        },
        staleness: "fresh",
      },
      {
        key: "local_preference_context",
        value: "local context anchored around Istanbul, Kadikoy",
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "environmental",
        },
        staleness: "fresh",
      },
    ],
  });

  assert.ok(planningHints.behavioralHints.some((item) => item.includes("compact time-boxed")));
  assert.ok(planningHints.environmentHints.some((item) => item.includes("Istanbul")));
});
