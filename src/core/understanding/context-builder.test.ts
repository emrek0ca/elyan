import assert from "node:assert/strict";
import test from "node:test";
import { classifyIntent } from "./intent-classifier.js";
import {
  buildUserContext,
  buildUserContextFromMemory,
  selectContinuityMemory,
  selectMemoryByRelevance,
  MEMORY_RELEVANCE_MODERATE_THRESHOLD,
  MEMORY_RELEVANCE_STRONG_THRESHOLD,
} from "./context-builder.js";
import { buildContextPacketsFromMetadata } from "./context-packets.js";

class FakeUnderstandingCacheStore {
  public readonly values = new Map<string, string>();
  public readonly ttlMs = new Map<string, number | undefined>();

  async get(key: string) {
    return this.values.get(key) ?? null;
  }

  async set(key: string, value: string, ttlMs?: number) {
    this.values.set(key, value);
    this.ttlMs.set(key, ttlMs);
  }
}

class FakeUnderstandingDb {
  public profileSelects = 0;
  public identitySelects = 0;
  public worldSelects = 0;

  select(fields: Record<string, unknown>) {
    const kind =
      "signalId" in fields
        ? "world"
        : "planCode" in fields || "subscriptionStatus" in fields
          ? "profile"
          : "displayName" in fields
            ? "identity"
            : "learning";
    const self = this;
    const builder = {
      from() {
        return builder;
      },
      leftJoin() {
        return builder;
      },
      where() {
        return builder;
      },
      orderBy() {
        return builder;
      },
      limit() {
        if (kind === "profile") {
          self.profileSelects += 1;
          return Promise.resolve([
            {
              displayName: "Emre",
              planCode: "solo",
              subscriptionStatus: "active",
            },
          ]);
        }
        if (kind === "identity") {
          self.identitySelects += 1;
          return Promise.resolve([{ displayName: "Identity Name" }]);
        }
        if (kind === "world") {
          self.worldSelects += 1;
          return Promise.resolve([
            {
              signalId: "signal-1",
              source: "mobile",
              kind: "time_context",
              summary: "Morning focus window",
              confidenceBps: 900,
              facts: {},
              privacy: "safe",
              renderHints: {},
              visibility: "assistant_context",
              createdAt: new Date("2030-01-01T08:00:00.000Z"),
            },
          ]);
        }
        return Promise.resolve([]);
      },
    };
    return builder;
  }
}

test("buildUserContextFromMemory deduplicates and caps prompt hints", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Fix Fastify code",
  });
  const memory = Array.from({ length: 20 }, (_, index) => ({
    id: String(index),
    type: index % 2 === 0 ? "style" : "technical_stack",
    key: index % 2 === 0 ? "answer_length" : "stack",
    value: index % 2 === 0 ? "concise" : `typescript_${index}`,
    confidence: 0.9,
    scope: "user",
    source: "interaction",
    createdAt: new Date(),
    staleness: "fresh" as const,
    conflictStatus: "active" as const,
    lastVerifiedAt: new Date(),
    importanceScore: 80,
    isPinned: false,
  }));

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Fix Fastify code",
      metadata: {
        projectName: "Elyan",
      },
    },
    memory,
    profile: {
      displayName: "Osman Emre",
      planCode: "pro",
      subscriptionStatus: "active",
    },
  });

  const hintCount =
    context.personalizationHints.length +
    context.projectHints.length +
    context.styleHints.length +
    context.technicalHints.length +
    context.safetyHints.length;

  assert.ok(hintCount <= context.tokenBudget.maxHints);
  assert.equal(context.styleHints.filter((hint) => hint.includes("answer_length: concise")).length, 1);
  assert.ok(context.projectHints.includes("project:Elyan"));
  assert.ok(context.ecosystemHints.includes("elyan_ecosystem"));
  assert.ok(context.ecosystemHints.includes("backend_control_plane"));
  assert.equal(context.taskFrame.reasoningMode, "balanced");
  assert.equal(context.userProfile?.displayName, "Osman Emre");
  assert.equal(context.userProfile?.planCode, "pro");
  assert.equal(context.userProfile?.subscriptionStatus, "active");
});

test("buildUserContext caches profile and world signals per user", async () => {
  const db = new FakeUnderstandingDb();
  const cache = new FakeUnderstandingCacheStore();
  const app = {
    db,
    config: {
      ELYAN_WORLD_CONTEXT_PACKETS_ENABLED: true,
    },
    services: {
      reliability: {
        store: cache,
      },
    },
  };
  const intent = classifyIntent({
    userId: "user-a",
    message: "Pil durumum sohbeti etkiler mi?",
  });
  const metadata = {
    memoryEnabled: false,
    chatContext: {
      lastDerivedContextDigest: {
        worldSignals: [
          {
            signalId: "device-current",
            kind: "device",
            summary: "Pil düşük, ağ wifi.",
            confidence: 0.8,
            createdAt: new Date().toISOString(),
            facts: { batteryLevel: 0.2, connectivity: "wifi" },
          },
        ],
      },
    },
  };

  await buildUserContext(app as never, {
    userId: "user-a",
    message: "Pil durumum sohbeti etkiler mi?",
    metadata,
    intent,
  });
  await buildUserContext(app as never, {
    userId: "user-a",
    message: "Pil durumum sohbeti etkiler mi?",
    metadata,
    intent,
  });

  assert.equal(db.profileSelects, 1);
  assert.equal(db.identitySelects, 1);
  assert.equal(db.worldSelects, 1);
  assert.equal(cache.ttlMs.get("understanding:profile:user-a"), 60_000);
  assert.equal(cache.ttlMs.get("understanding:world:user-a:global"), 30_000);

  const intentB = classifyIntent({
    userId: "user-b",
    message: "Pil durumum sohbeti etkiler mi?",
  });
  await buildUserContext(app as never, {
    userId: "user-b",
    message: "Pil durumum sohbeti etkiler mi?",
    metadata,
    intent: intentB,
  });

  assert.equal(db.profileSelects, 2);
  assert.equal(db.identitySelects, 2);
  assert.equal(db.worldSelects, 2);
  assert.equal(cache.values.has("understanding:profile:user-a"), true);
  assert.equal(cache.values.has("understanding:profile:user-b"), true);
  assert.equal(cache.values.has("understanding:world:user-a:global"), true);
  assert.equal(cache.values.has("understanding:world:user-b:global"), true);
});

test("buildUserContextFromMemory keeps only one correction-style memory and suppresses contested noise", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Answer briefly",
  });
  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Answer briefly",
    },
    memory: [
      {
        id: "fresh-style",
        type: "style",
        key: "answer_length",
        value: "concise",
        confidence: 0.95,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 90,
        isPinned: true,
      },
      {
        id: "correction-1",
        type: "correction",
        key: "negative_feedback",
        value: "avoid long answers",
        confidence: 0.9,
        scope: "user",
        source: "reflective_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 70,
        isPinned: false,
      },
      {
        id: "correction-2",
        type: "correction",
        key: "negative_feedback",
        value: "avoid vague phrasing",
        confidence: 0.91,
        scope: "user",
        source: "reflective_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 71,
        isPinned: false,
      },
      {
        id: "contested",
        type: "preference",
        key: "preferred_tone",
        value: "overly playful",
        confidence: 0.93,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "contested",
        conflictStatus: "contested",
        lastVerifiedAt: new Date(),
        importanceScore: 75,
        isPinned: false,
      },
    ],
    profile: {
      displayName: "Elyan User",
    },
  });

  assert.equal(context.safetyHints.length, 1);
  assert.equal(context.retrievedMemory.filter((item) => item.type === "correction").length, 1);
  assert.equal(context.retrievedMemory.some((item) => item.id === "contested"), false);
  assert.equal(context.taskFrame.shouldClarify, false);
  assert.equal(context.userProfile?.displayName, "Elyan User");
  assert.equal(context.userProfile?.preferredLanguage, null);
});

test("buildUserContextFromMemory derives preferred name and language from safe memory facts", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Uzun ve detaylı yaz.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Uzun ve detaylı yaz.",
    },
    profile: {
      displayName: "Osman",
      planCode: "solo",
    },
    memory: [
      {
        id: "identity-name",
        type: "identity",
        key: "preferred_name",
        value: "Emre",
        confidence: 0.97,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 90,
        isPinned: true,
      },
      {
        id: "lang",
        type: "preference",
        key: "preferred_language",
        value: "Türkçe",
        confidence: 0.96,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 88,
        isPinned: true,
      },
    ],
  });

  assert.equal(context.userProfile?.displayName, "Osman");
  assert.equal(context.userProfile?.preferredName, "Emre");
  assert.equal(context.userProfile?.preferredLanguage, "Türkçe");
  assert.equal(context.userProfile?.planCode, "solo");
  assert.deepEqual(context.situationalHints, []);
  assert.deepEqual(context.behavioralHints, []);
  assert.deepEqual(context.environmentHints, []);
  assert.ok(context.relationshipContextDigest.some((item) => item.includes("Emre")));
  assert.ok(context.relationshipContextDigest.some((item) => item.includes("Türkçe")));
  assert.ok((context.speakingStyleDirectives ?? []).some((item) => item.includes("Türkçe")));
});

test("buildUserContextFromMemory turns warm mature teaching style memory into scoped directives", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Bunu bana açıkla.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Bunu bana açıkla.",
    },
    profile: {
      displayName: "Emre",
    },
    memory: [
      {
        id: "style-warm-teaching",
        type: "style",
        key: "response_style_preference",
        value: "warm_close_mature_teaching",
        confidence: 0.96,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 90,
        isPinned: true,
      },
    ],
  });

  assert.ok(
    context.relationshipContextDigest.some((item) =>
      item.includes("warm, close, mature, explanatory"),
    ),
  );
  assert.ok(
    (context.speakingStyleDirectives ?? []).some((item) =>
      item.includes("warm, close, mature, explanatory"),
    ),
  );
  assert.ok(
    (context.speakingStyleDirectives ?? []).some((item) =>
      item.includes("not overdo intimacy"),
    ),
  );
});

test("buildUserContextFromMemory keeps the latest preferred name and suppresses stale aliases", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Selam",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Selam",
    },
    profile: {
      displayName: "Zeynep",
    },
    memory: [
      {
        id: "old-preferred-name",
        type: "identity",
        key: "preferred_name",
        value: "Zeynep",
        confidence: 0.99,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date("2026-07-04T00:00:00.000Z"),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date("2026-07-04T00:00:00.000Z"),
        importanceScore: 100,
        isPinned: true,
      },
      {
        id: "latest-preferred-name",
        type: "identity",
        key: "hitap şekli",
        value: "Emre",
        confidence: 0.91,
        scope: "user",
        source: "explicit_user",
        createdAt: new Date("2026-07-04T00:03:00.000Z"),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date("2026-07-04T00:03:00.000Z"),
        importanceScore: 70,
        isPinned: false,
      },
    ],
  });

  assert.equal(context.userProfile?.displayName, "Zeynep");
  assert.equal(context.userProfile?.preferredName, "Emre");
  assert.deepEqual(
    context.retrievedMemory
      .filter((item) => item.key === "preferred_name" || item.key === "name")
      .map((item) => item.value),
    ["Emre"],
  );
  assert.equal(context.personalizationHints.some((hint) => hint.includes("Zeynep")), false);
  assert.ok(context.personalizationHints.some((hint) => hint.includes("preferred_name: Emre")));
  assert.ok(context.relationshipContextDigest.some((item) => item.includes("Emre")));
  assert.equal(context.relationshipContextDigest.some((item) => item.includes("Zeynep")), false);
});

test("buildUserContextFromMemory ignores suspicious memory-derived names", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "hey",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "hey",
    },
    memory: [
      {
        id: "bad-name",
        type: "identity",
        key: "preferred_name",
        value: "Attım Bugün Kaç",
        confidence: 0.96,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 95,
        isPinned: true,
      },
    ],
    profile: null,
  });

  assert.equal(context.userProfile?.preferredName ?? null, null);
  assert.equal(context.relationshipContextDigest.some((item) => item.includes("Attım Bugün Kaç")), false);
});

test("buildUserContextFromMemory suppresses world-derived memory without a current authorized packet", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Bugün planımı buna göre ayarla.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Bugün planımı buna göre ayarla.",
    },
    memory: [
      {
        id: "derived-energy",
        type: "workflow",
        key: "energy_rhythm",
        value: "low energy window; prefer shorter, lower-friction steps",
        confidence: 0.91,
        scope: "user",
        source: "system",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 80,
        isPinned: false,
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "situational",
        },
      },
      {
        id: "derived-plan",
        type: "workflow",
        key: "preferred_planning_granularity",
        value: "prefers compact time-boxed steps on busy days",
        confidence: 0.89,
        scope: "user",
        source: "system",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 78,
        isPinned: false,
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "behavioral",
        },
      },
    ],
  });

  assert.equal(context.situationalHints.some((hint) => hint.includes("low energy window")), false);
  assert.equal(context.behavioralHints.some((hint) => hint.includes("compact time-boxed")), false);
  assert.equal(context.memorySnapshot?.derivedFacts.length, 0);
});

test("buildUserContextFromMemory builds a clean continuity digest and memory shortlist", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Bugünkü planımı kısa ve net çıkar.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Bugünkü planımı kısa ve net çıkar.",
      metadata: {
        dialogueStateSource: "server_dialogue_state.v1",
        dialogueStateUserId: "user_1",
        compactContext: {
          source: "server_dialogue_state.v1",
          ownerUserId: "user_1",
          rollingSummary: {
            userGoal: "Haftalık çalışma sistemini toparlamak",
            assistantState: "Önceki turda kaba plan çıkarıldı",
            openLoops: ["Takvime göre net günlük plan çıkarmak"],
          },
          recentMessages: [
            { role: "user", content: "Haftalık çalışma sistemimi toparla ve günlük plan çıkar" },
            { role: "assistant", content: "Önce haftalık çerçeveyi kurup sonra günlük planı netleştirelim." },
          ],
        },
      },
    },
    profile: {
      displayName: "Emre",
      preferredLanguage: "Türkçe",
    },
    memory: [
      {
        id: "pref-length",
        type: "preference",
        key: "answer_length",
        value: "concise",
        confidence: 0.95,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 91,
        isPinned: true,
      },
      {
        id: "project",
        type: "project_context",
        key: "active_project",
        value: "Elyan backend personalization",
        confidence: 0.91,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 84,
        isPinned: false,
      },
      {
        id: "world-derived",
        type: "workflow",
        key: "common_city",
        value: "Istanbul",
        confidence: 0.88,
        scope: "user",
        source: "system",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 76,
        isPinned: false,
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "environmental",
        },
      },
    ],
  });

  assert.ok(context.relationshipContextDigest.some((item) => item.includes("Emre")));
  assert.ok(context.relationshipContextDigest.some((item) => item.includes("Haftalık çalışma sistemini toparlamak")));
  assert.ok(context.relationshipContextDigest.some((item) => item.includes("Takvime göre net günlük plan çıkarmak")));
  assert.ok(context.memoryRelevanceSummary.includes("answer_length: concise"));
  assert.ok(context.memoryRelevanceSummary.includes("active_project: Elyan backend personalization"));
  assert.equal(context.memoryRelevanceSummary.some((item) => item.includes("Istanbul")), false);
  assert.equal(context.continuityBoundary?.mode, "same_topic");
  assert.equal(context.continuityBoundary?.carryContinuity, true);
});

test("selectContinuityMemory keeps only user-scoped safe continuity facts and caps noisy categories", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Backend tarafında auth akışını düzelt.",
  });

  const selected = selectContinuityMemory({
    queryTokens: new Set(["backend", "auth", "akış"]),
    intent,
    continuitySummary: {
      userGoal: "Auth akışını düzeltmek",
      assistantState: null,
      openLoops: ["403 hatasının kök nedenini bulmak"],
    },
    continuityBoundary: {
      mode: "same_topic",
      reason: "test",
      carryContinuity: true,
    },
    memory: [
      {
        id: "shared-project",
        type: "project_context",
        key: "project_name",
        value: "Global tenant memory",
        confidence: 0.99,
        scope: "shared",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 95,
        isPinned: true,
      },
      {
        id: "world-derived",
        type: "workflow",
        key: "common_city",
        value: "Istanbul",
        confidence: 0.9,
        scope: "user",
        source: "system",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 70,
        isPinned: false,
        metadata: {
          sourceCategory: "world_signal_derived",
          derivedTraitCategory: "environmental",
        },
      },
      {
        id: "episode-1",
        type: "episodic",
        key: "recent_issue",
        value: "auth callback 403 hatası konuşuldu",
        confidence: 0.9,
        scope: "user",
        source: "episodic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: null,
        importanceScore: 80,
        isPinned: false,
      },
      {
        id: "episode-2",
        type: "episodic",
        key: "recent_issue_2",
        value: "session refresh bug araştırıldı",
        confidence: 0.88,
        scope: "user",
        source: "episodic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: null,
        importanceScore: 79,
        isPinned: false,
      },
      {
        id: "tech-1",
        type: "technical_stack",
        key: "stack",
        value: "fastify auth pipeline",
        confidence: 0.92,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 84,
        isPinned: true,
      },
      {
        id: "tech-2",
        type: "technical_stack",
        key: "stack_2",
        value: "jwt refresh handling",
        confidence: 0.9,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 82,
        isPinned: false,
      },
      {
        id: "tech-3",
        type: "technical_stack",
        key: "stack_3",
        value: "postgres audit trail",
        confidence: 0.89,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 81,
        isPinned: false,
      },
    ],
  });

  assert.equal(selected.some((item) => item.scope === "shared"), false);
  assert.equal(selected.some((item) => item.metadata?.sourceCategory === "world_signal_derived"), false);
  assert.equal(selected.filter((item) => item.source === "episodic_memory").length, 1);
  assert.ok(selected.some((item) => item.key === "stack"));
  assert.ok(selected.some((item) => item.key === "stack_2"));
  assert.equal(selected.some((item) => item.key === "stack_3"), false);
});

test("buildUserContextFromMemory suppresses stale continuity when the user clearly shifts topic", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Bana kısa bir şiir yaz.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Bana kısa bir şiir yaz.",
      metadata: {
        dialogueStateSource: "server_dialogue_state.v1",
        dialogueStateUserId: "user_1",
        compactContext: {
          source: "server_dialogue_state.v1",
          ownerUserId: "user_1",
          rollingSummary: {
            userGoal: "Backend auth bugını düzeltmek",
            assistantState: "Root cause aranıyordu",
            openLoops: ["403 hatasını doğrulamak"],
          },
          recentMessages: [
            { role: "user", content: "Backend auth bugını düzelt" },
            { role: "assistant", content: "Önce root cause bulalım." },
          ],
        },
      },
    },
    profile: {
      displayName: "Emre",
    },
    memory: [
      {
        id: "pref-tone",
        type: "preference",
        key: "preferred_tone",
        value: "warm_professional",
        confidence: 0.92,
        scope: "user",
        source: "semantic_memory",
        createdAt: new Date(),
        staleness: "fresh",
        conflictStatus: "active",
        lastVerifiedAt: new Date(),
        importanceScore: 85,
        isPinned: true,
      },
    ],
  });

  assert.equal(context.continuityBoundary?.mode, "possible_shift");
  assert.equal(context.continuityBoundary?.carryContinuity, false);
  assert.equal(context.relationshipContextDigest.some((item) => item.includes("Backend auth")), false);
  assert.equal(context.memoryRelevanceSummary.some((item) => item.includes("open_follow_up")), false);
  assert.ok((context.speakingStyleDirectives ?? []).some((item) => item.includes("Do not drag prior chat context")));
  assert.ok((context.reasoningDirectives ?? []).some((item) => item.includes("optional background")));
});

test("buildUserContextFromMemory carries continuity from canonical turn traces", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Buna göre ikinci öneriyi daha samimi yap.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Buna göre ikinci öneriyi daha samimi yap.",
      metadata: {
        dialogueStateSource: "server_dialogue_state.v1",
        dialogueStateUserId: "user_1",
        compactContext: {
          source: "server_dialogue_state.v1",
          ownerUserId: "user_1",
          turns: [
            {
              at: "2030-01-01T12:00:00.000Z",
              user: "Üç farklı onboarding mesajı öner.",
              assistant: "Birinci mesaj net, ikinci mesaj daha sıcak, üçüncü mesaj daha kurumsal olabilir.",
              workload: "mobile_chat_fast",
            },
          ],
        },
      },
    },
    profile: {
      displayName: "Emre",
    },
    memory: [],
  });

  assert.equal(context.continuityBoundary?.mode, "same_topic");
  assert.equal(context.continuityBoundary?.reason, "referential_followup");
  assert.equal(context.continuityBoundary?.carryContinuity, true);
  assert.match(context.continuitySummary.userGoal ?? "", /onboarding mesajı/);
  assert.match(context.continuitySummary.assistantState ?? "", /ikinci mesaj/);
  assert.ok(context.relationshipContextDigest.some((item) => item.includes("Continuing user goal")));
});

test("buildUserContextFromMemory links later turns by session turn overlap", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Auth timeout çözümünü Redis tarafına uyarla.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Auth timeout çözümünü Redis tarafına uyarla.",
      metadata: {
        dialogueStateSource: "server_dialogue_state.v1",
        dialogueStateUserId: "user_1",
        compactContext: {
          source: "server_dialogue_state.v1",
          ownerUserId: "user_1",
          turns: [
            {
              at: "2030-01-01T12:00:00.000Z",
              user: "Backend auth timeout hatasını nasıl çözeriz?",
              assistant: "Önce timeout kaynağını izole edip retry ve guard eklemek gerekir.",
              workload: "debugging",
            },
          ],
        },
      },
    },
    memory: [],
  });

  assert.equal(context.continuityBoundary?.mode, "same_topic");
  assert.equal(context.continuityBoundary?.reason, "session_turn_overlap");
  assert.equal(context.continuityBoundary?.carryContinuity, true);
  assert.ok(context.memoryRelevanceSummary.some((item) => item.includes("current_goal")));
});

test("buildUserContextFromMemory uses salience to keep long-session intent alive cheaply", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Redis kısmını aynı mantıkla güncelle.",
  });

  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Redis kısmını aynı mantıkla güncelle.",
      metadata: {
        dialogueStateSource: "server_dialogue_state.v1",
        dialogueStateUserId: "user_1",
        compactContext: {
          source: "server_dialogue_state.v1",
          ownerUserId: "user_1",
          salience: {
            topics: ["auth", "timeout", "redis"],
            entities: ["Redis", "Fastify"],
            userIntent: "Auth timeout çözümünü kalıcı hale getirmek.",
            assistantCommitment: "Retry guard mantığını Redis tarafına uyarlayacağım.",
            emotionalTone: "focused",
            unresolved: true,
          },
        },
      },
    },
    memory: [],
  });

  assert.equal(context.continuityBoundary?.mode, "same_topic");
  assert.equal(context.continuityBoundary?.reason, "referential_followup");
  assert.match(context.continuitySummary.userGoal ?? "", /Auth timeout/);
  assert.match(context.continuitySummary.assistantState ?? "", /Retry guard/);
  assert.ok(context.situationalHints.some((hint) => hint.includes("auth, timeout, redis")));
  assert.ok(context.situationalHints.some((hint) => hint.includes("Redis, Fastify")));
  assert.ok(context.behavioralHints.some((hint) => hint.includes("Retry guard")));
  assert.ok(context.behavioralHints.some((hint) => hint.includes("focused")));
});

test("buildContextPacketsFromMetadata packages health signals without raw measurements", () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const packets = buildContextPacketsFromMetadata(
    {
      chatContext: {
        lastDerivedContextDigest: {
          worldSignals: [
            {
              signalId: "health-1",
              kind: "health",
              summary: "Nabız 90 bpm, uyku 7 saat, enerji iyi.",
              confidence: 0.91,
              createdAt: "2030-01-01T11:30:00.000Z",
              privacy: { backendPlaintextAllowed: true },
              facts: {
                readiness: 0.82,
                stressLevel: "orta",
                heartRateBpm: 90,
                sleepDuration: 7,
              },
            },
          ],
        },
      },
    },
    { now },
  );

  assert.equal(packets.length, 1);
  assert.equal(packets[0]?.kind, "health_context");
  assert.equal(packets[0]?.privacyClass, "health_ephemeral");
  assert.equal(packets[0]?.freshness, "fresh");
  assert.match(packets[0]?.summary ?? "", /readiness=high/);
  assert.match(packets[0]?.summary ?? "", /stress=orta/);
  assert.doesNotMatch(packets[0]?.summary ?? "", /90|bpm|7 saat|heartRate|sleepDuration|teşhis|diagnosis/i);
});

test("buildContextPacketsFromMetadata packages calendar device notification and time signals safely", () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const packets = buildContextPacketsFromMetadata(
    {
      chatContext: {
        lastDerivedContextDigest: {
          worldSignals: [
            {
              signalId: "calendar-1",
              kind: "calendar",
              summary: "Bugün yoğun ama öğleden sonra kısa bir odak aralığı var.",
              confidence: 0.86,
              createdAt: "2030-01-01T10:30:00.000Z",
              privacy: { backendPlaintextAllowed: true },
              facts: {
                meetingLoad: "orta",
                focusWindow: "öğleden sonra",
                eventTitle: "Gizli toplantı başlığı",
              },
            },
            {
              signalId: "device-1",
              kind: "device",
              summary: "Cihaz çevrimiçi, pil düşük güç moduna yakın.",
              confidence: 0.8,
              createdAt: "2030-01-01T11:45:00.000Z",
              facts: {
                batteryLevel: 0.31,
                connectivity: "wifi",
                lowPowerMode: false,
              },
            },
            {
              signalId: "notification-1",
              kind: "notification",
              summary: "Bildirim gövdesi: banka mesajı ve özel içerik",
              confidence: 0.77,
              createdAt: "2030-01-01T11:50:00.000Z",
              facts: {
                notificationLoad: "yüksek",
                urgency: "orta",
                messageBody: "özel mesaj",
              },
            },
            {
              signalId: "time-1",
              kind: "time",
              summary: "Yerel saat öğle sonrası.",
              confidence: 0.93,
              createdAt: "2030-01-01T11:55:00.000Z",
              facts: {
                timezone: "Europe/Istanbul",
                dayPart: "öğle sonrası",
                workingHours: true,
              },
            },
          ],
        },
      },
    },
    { now },
  );

  assert.deepEqual(
    packets.map((packet) => packet.kind),
    ["time_context", "notification_context", "device_context", "calendar_context"],
  );
  assert.match(packets.find((packet) => packet.kind === "calendar_context")?.summary ?? "", /meeting_load=orta/);
  assert.match(packets.find((packet) => packet.kind === "device_context")?.summary ?? "", /battery=low/);
  assert.match(packets.find((packet) => packet.kind === "notification_context")?.summary ?? "", /notification_signal=recent/);
  assert.match(packets.find((packet) => packet.kind === "time_context")?.summary ?? "", /timezone=Europe\/Istanbul/);
  assert.doesNotMatch(
    packets.map((packet) => packet.summary).join("\n"),
    /Gizli toplantı başlığı|özel mesaj|banka mesajı|messageBody|eventTitle/i,
  );
});

test("buildContextPacketsFromMetadata suppresses irrelevant world context in greetings", () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const packets = buildContextPacketsFromMetadata(
    {
      chatContext: {
        lastDerivedContextDigest: {
          worldSignals: [
            {
              signalId: "health-1",
              kind: "health",
              summary: "Enerji orta, adım sayısı yüksek.",
              confidence: 0.9,
              createdAt: "2030-01-01T11:55:00.000Z",
              facts: { energy: "orta", readiness: 0.7 },
            },
            {
              signalId: "device-1",
              kind: "device",
              summary: "Pil düşük, ağ wifi.",
              confidence: 0.8,
              createdAt: "2030-01-01T11:56:00.000Z",
              facts: { batteryLevel: 0.2, connectivity: "wifi" },
            },
            {
              signalId: "location-1",
              kind: "location",
              summary: "Konum: Kayseri, Türkiye.",
              confidence: 0.82,
              createdAt: "2030-01-01T11:57:00.000Z",
              facts: { city: "Kayseri", country: "Türkiye" },
            },
          ],
        },
      },
    },
    { now, requestText: "Selam", intent: "chat" },
  );

  assert.equal(packets.length, 0);
});

test("buildContextPacketsFromMetadata does not inject live context into creative short prompts", () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const packets = buildContextPacketsFromMetadata(
    {
      chatContext: {
        lastDerivedContextDigest: {
          worldSignals: [
            {
              signalId: "location-1",
              kind: "location",
              summary: "Konum: Kayseri, Türkiye.",
              confidence: 0.82,
              createdAt: "2030-01-01T11:57:00.000Z",
              facts: { city: "Kayseri", country: "Türkiye" },
            },
            {
              signalId: "time-1",
              kind: "time",
              summary: "Yerel saat öğle sonrası.",
              confidence: 0.93,
              createdAt: "2030-01-01T11:58:00.000Z",
              facts: { dayPart: "öğle sonrası" },
            },
          ],
        },
      },
    },
    {
      now,
      requestText: "Bana çok bilinmeyen en garip hayvan ismini söyle",
      intent: "chat",
    },
  );

  assert.equal(packets.length, 0);
});

test("buildContextPacketsFromMetadata exposes only relevant world context", () => {
  const now = new Date("2030-01-01T12:00:00.000Z");
  const baseSignals = {
    chatContext: {
      lastDerivedContextDigest: {
        worldSignals: [
          {
            signalId: "device-1",
            kind: "device",
            summary: "Pil düşük, ağ wifi.",
            confidence: 0.8,
            createdAt: "2030-01-01T11:56:00.000Z",
            facts: { batteryLevel: 0.2, connectivity: "wifi" },
          },
          {
            signalId: "health-1",
            kind: "health",
            summary: "Enerji orta, uyku düşük.",
            confidence: 0.9,
            createdAt: "2030-01-01T11:55:00.000Z",
            privacy: { backendPlaintextAllowed: true },
            facts: { energy: "orta", sleepQuality: "düşük" },
          },
          {
            signalId: "location-1",
            kind: "location",
            summary: "Konum: Kayseri, Türkiye.",
            confidence: 0.82,
            createdAt: "2030-01-01T11:57:00.000Z",
            privacy: { backendPlaintextAllowed: true },
            facts: { city: "Kayseri", country: "Türkiye" },
          },
        ],
      },
    },
  };

  const devicePackets = buildContextPacketsFromMetadata(baseSignals, {
    now,
    requestText: "Pil durumum sohbeti etkiler mi?",
    intent: "chat",
  });
  assert.equal(devicePackets.find((packet) => packet.kind === "device_context")?.mentionPolicy, "explicit_when_relevant");
  assert.equal(devicePackets.find((packet) => packet.kind === "health_context"), undefined);

  const planningPackets = buildContextPacketsFromMetadata(baseSignals, {
    now,
    requestText: "Bugün çalışma planı çıkar.",
    intent: "planning",
  });
  assert.equal(planningPackets.find((packet) => packet.kind === "health_context")?.mentionPolicy, "implicit");
  assert.equal(planningPackets.find((packet) => packet.kind === "world_context")?.mentionPolicy, "implicit");
  assert.equal(
    planningPackets.find((packet) => packet.kind === "world_context")?.relevanceReason,
    "location_context_for_logistics_only",
  );

  const localPackets = buildContextPacketsFromMetadata(baseSignals, {
    now,
    requestText: "Kayseri civarında yemek öner.",
    intent: "chat",
  });
  assert.equal(localPackets.find((packet) => packet.kind === "world_context")?.mentionPolicy, "explicit_when_relevant");
  assert.match(localPackets.find((packet) => packet.kind === "world_context")?.summary ?? "", /city=Kayseri/);
});

test("buildContextPacketsFromMetadata exposes time context for technical work pacing", () => {
  const now = new Date("2030-01-01T23:15:00.000Z");
  const packets = buildContextPacketsFromMetadata(
    {
      chatContext: {
        lastDerivedContextDigest: {
          worldSignals: [
            {
              signalId: "time-late-1",
              kind: "time",
              summary: "Yerel saat gece geç; kısa ve uygulanabilir cevap iyi olur.",
              confidence: 0.91,
              createdAt: "2030-01-01T23:10:00.000Z",
              facts: {
                timezone: "Europe/Istanbul",
                localTime: "02:10",
                dayPart: "gece geç",
                workingHours: false,
              },
            },
          ],
        },
      },
    },
    {
      now,
      requestText: "TypeScript kodunda bu hatayı debug et.",
      intent: "debugging",
    },
  );

  const timePacket = packets.find((packet) => packet.kind === "time_context");
  assert.equal(timePacket?.mentionPolicy, "implicit");
  assert.equal(timePacket?.relevanceReason, "time_context_for_work_pacing_only");
  assert.match(timePacket?.summary ?? "", /local_time=02:10/);
  assert.ok(timePacket?.allowedUse?.includes("adjust brevity and timing without naming the context"));
});

test("buildContextPacketsFromMetadata reads world signals from mobile memory snapshots", () => {
  const packets = buildContextPacketsFromMetadata(
    {
      memorySnapshot: {
        recentSignals: [
          {
            kind: "location",
            summary: "Konum: İstanbul, Kadıköy, Türkiye.",
            confidence: 0.82,
            createdAt: "2030-01-01T11:59:00.000Z",
            facts: { city: "İstanbul", district: "Kadıköy", country: "Türkiye" },
            privacy: { precision: "coarse", backendPlaintextAllowed: true },
          },
        ],
      },
    },
    {
      now: new Date("2030-01-01T12:00:00.000Z"),
      requestText: "Şu an neredeyim?",
      intent: "chat",
    },
  );

  assert.equal(packets.length, 1);
  assert.equal(packets[0]?.kind, "world_context");
  assert.equal(packets[0]?.mentionPolicy, "explicit_when_relevant");
  assert.match(packets[0]?.summary ?? "", /İstanbul/);
  assert.match(packets[0]?.summary ?? "", /district=Kadıköy/);
});

test("buildContextPacketsFromMetadata reports requested mobile context availability without web substitution", () => {
  const healthPackets = buildContextPacketsFromMetadata(
    {
      compactContext: {
        mobileContextCapabilities: {
          healthEnabled: true,
          healthSignalsAvailable: false,
        },
      },
    },
    { requestText: "Sağlık verilerim nedir?", intent: "chat" },
  );
  const healthPacket = healthPackets.find((packet) => packet.kind === "health_context");
  assert.equal(healthPacket?.relevanceReason, "health_context_unavailable");
  assert.equal(healthPacket?.mentionPolicy, "explicit_when_relevant");
  assert.match(healthPacket?.summary ?? "", /no current authorized health signal/i);
  assert.ok(healthPacket?.allowedUse?.some((use) => use.includes("do not substitute web results")));

  const locationPackets = buildContextPacketsFromMetadata(
    {
      compactContext: {
        mobileContextCapabilities: {
          locationEnabled: false,
          locationSignalsAvailable: false,
        },
      },
    },
    { requestText: "Şu an neredeyim?", intent: "chat" },
  );
  const locationPacket = locationPackets.find((packet) => packet.kind === "world_context");
  assert.equal(locationPacket?.relevanceReason, "location_context_disabled");
  assert.match(locationPacket?.summary ?? "", /disabled in Elyan app settings/i);
  assert.ok(locationPacket?.allowedUse?.some((use) => use.includes("do not infer")));
});

test("buildContextPacketsFromMetadata does not mistake generic technical words for personal context requests", () => {
  const metadata = {
    compactContext: {
      mobileContextCapabilities: {
        healthEnabled: true,
        calendarEnabled: true,
        healthSignalsAvailable: false,
        calendarSignalsAvailable: false,
      },
    },
  };

  for (const requestText of [
    "Kuantumu adım adım anlat",
    "Yapay sinir ağlarında performansı artır",
    "Event loop nedir?",
    "Bir sunum hazırla",
  ]) {
    assert.equal(
      buildContextPacketsFromMetadata(metadata, { requestText, intent: "chat" }).length,
      0,
    );
  }
});

test("buildContextPacketsFromMetadata does not add availability packet when the requested signal exists", () => {
  const packets = buildContextPacketsFromMetadata(
    {
      compactContext: {
        mobileContextCapabilities: {
          locationEnabled: true,
          locationSignalsAvailable: true,
        },
        derivedContextDigest: {
          worldSignals: [
            {
              signalId: "location-current",
              kind: "location",
              summary: "Konum: Ankara, Türkiye.",
              confidence: 0.9,
              createdAt: "2030-01-01T11:59:00.000Z",
              facts: { city: "Ankara", country: "Türkiye" },
              privacy: { backendPlaintextAllowed: true },
            },
          ],
        },
      },
    },
    {
      now: new Date("2030-01-01T12:00:00.000Z"),
      requestText: "Şu an neredeyim?",
      intent: "chat",
    },
  );

  assert.equal(packets.filter((packet) => packet.kind === "world_context").length, 1);
  assert.equal(packets[0]?.signalKinds.includes("location"), true);
  assert.equal(packets[0]?.signalKinds.includes("location_availability"), false);
});

test("buildContextPacketsFromMetadata rejects cached sensitive signals after mobile permission is disabled", () => {
  const packets = buildContextPacketsFromMetadata(
    {
      compactContext: {
        mobileContextCapabilities: {
          locationEnabled: false,
          locationSignalsAvailable: false,
        },
        derivedContextDigest: {
          worldSignals: [
            {
              signalId: "location-disabled-cache",
              kind: "location",
              summary: "Konum: Ankara, Türkiye.",
              confidence: 0.9,
              createdAt: "2030-01-01T11:59:00.000Z",
              facts: { city: "Ankara", country: "Türkiye" },
              privacy: { backendPlaintextAllowed: true },
            },
          ],
        },
      },
    },
    {
      now: new Date("2030-01-01T12:00:00.000Z"),
      requestText: "Şu an neredeyim?",
      intent: "chat",
    },
  );

  assert.equal(packets.length, 1);
  assert.equal(packets[0]?.relevanceReason, "location_context_disabled");
  assert.doesNotMatch(packets[0]?.summary ?? "", /Ankara/);
});

test("buildUserContextFromMemory exposes packet flags and health safety hint", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Bugünkü durumumu değerlendir.",
  });
  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Bugünkü durumumu değerlendir.",
    },
    memory: [],
    contextPackets: [
      {
        kind: "health_context",
        source: "world_signal",
        title: "Kısa ömürlü sağlık bağlamı",
        summary: "enerji: orta; stres: düşük",
        confidence: 0.8,
        freshness: "fresh",
        privacyClass: "health_ephemeral",
        evidenceCount: 2,
        createdAt: "2030-01-01T11:30:00.000Z",
        expiresAt: "2030-01-02T11:30:00.000Z",
        renderHint: "context_signal",
        signalKinds: ["health"],
      },
    ],
  });

  assert.equal(context.contextPackets.length, 1);
  assert.equal(context.healthContextUsed, true);
  assert.deepEqual(context.packetKinds, ["health_context"]);
  assert.ok(context.safetyHints.some((hint) => hint.includes("short-lived wellbeing/readiness")));
});

test("buildUserContextFromMemory carries explicit user personalization prompt from settings metadata", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Bugun nasil ilerleyelim?",
  });
  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Bugun nasil ilerleyelim?",
      metadata: {
        userPersonalizationPrompt:
          "Benimle dogal, samimi ve net Turkce konus. Gereksiz uzatma.",
      },
    },
    memory: [],
    profile: {
      displayName: "Emre",
    },
  });

  assert.equal(
    context.personalizationPrompt,
    "Benimle dogal, samimi ve net Turkce konus. Gereksiz uzatma.",
  );
  assert.ok(
    context.personalizationHints.some((hint) =>
      hint.includes("Explicit user personalization from settings"),
    ),
  );
});

test("buildUserContextFromMemory applies current affect and channel provenance without making them routing authority", () => {
  const intent = classifyIntent({
    userId: "user_1",
    message: "Bu çalışmıyor, çok yoruldum.",
  });
  const context = buildUserContextFromMemory({
    userId: "user_1",
    accountId: "user_1",
    intent,
    task: {
      userId: "user_1",
      message: "Bu çalışmıyor, çok yoruldum.",
      source: "whatsapp",
      metadata: {},
    },
    memory: [],
    currentAffect: {
      mood: "tired",
      energy: "low",
      confidence: 0.82,
      source: "typed_fallback",
      responseDirective:
        "Keep cognitive load low: short sentences and clear ordering.",
    },
  });

  assert.equal(context.interactionContext.channel, "whatsapp");
  assert.equal(context.interactionContext.profileScope, "canonical_user");
  assert.equal(context.currentAffect?.mood, "tired");
  assert.ok(
    context.speakingStyleDirectives?.some((item) =>
      item.includes("cognitive load low"),
    ),
  );
  assert.equal(
    context.behavioralHints.some((item) =>
      item.includes("Current-turn affect: tired"),
    ),
    false,
  );
});

test("clarificationDiagnostics: short follow-up with prior turn context resolves silently", () => {
  // "onu düzelt" tek başına belirsiz, ama önceki turun userGoal +
  // assistantState + openLoops'u varsa cevap iyi tanımlı (önceki çıktıyı
  // revize et) — modelden gereksiz yere netleştirme sorusu istenmemeli.
  const intent = classifyIntent({ userId: "u1", message: "onu düzelt" });
  const context = buildUserContextFromMemory({
    userId: "u1",
    accountId: "u1",
    intent,
    task: {
      userId: "u1",
      message: "onu düzelt",
      metadata: {
        dialogueStateSource: "server_dialogue_state.v1",
        dialogueStateUserId: "u1",
        compactContext: {
          source: "server_dialogue_state.v1",
          ownerUserId: "u1",
          rollingSummary: {
            userGoal: "Kısa release notu hazırlamak",
            assistantState: "İlk taslak çıkarıldı",
            openLoops: ["Başlık ve maddeleri netleştirmek"],
          },
        },
      },
    },
    memory: [],
    profile: { displayName: "Emre" },
  });

  assert.equal(context.clarificationDiagnostics.shouldClarify, false);
  assert.equal(
    context.clarificationDiagnostics.reason,
    "short_followup_resolved_by_prior_turn_context",
  );
});

test("clarificationDiagnostics ignores untrusted compactContext from another account", () => {
  const intent = classifyIntent({ userId: "u2", message: "onu düzelt" });
  const context = buildUserContextFromMemory({
    userId: "u2",
    accountId: "u2",
    intent,
    task: {
      userId: "u2",
      message: "onu düzelt",
      metadata: {
        compactContext: {
          rollingSummary: {
            userGoal: "Other account release notes",
            assistantState: "Other account draft exists",
            openLoops: ["Other account private loop"],
          },
        },
      },
    },
    memory: [],
    profile: { displayName: "Ayşe" },
  });

  assert.equal(context.continuitySummary.userGoal, null);
  assert.deepEqual(context.continuitySummary.openLoops, []);
  assert.equal(context.clarificationDiagnostics.shouldClarify, true);
  assert.equal(context.clarificationDiagnostics.ambiguityKind, "ambiguous_followup");
});

test("clarificationDiagnostics: short follow-up WITHOUT prior context flags ambiguous_followup", () => {
  // Aynı mesaj bağlam yokken belirsiz — model kısa hatırlatma istemeli.
  const intent = classifyIntent({ userId: "u1", message: "devam et" });
  const context = buildUserContextFromMemory({
    userId: "u1",
    accountId: "u1",
    intent,
    task: { userId: "u1", message: "devam et", metadata: {} },
    memory: [],
    profile: { displayName: "Emre" },
  });

  assert.equal(context.clarificationDiagnostics.shouldClarify, true);
  assert.equal(context.clarificationDiagnostics.ambiguityKind, "ambiguous_followup");
  assert.equal(
    context.clarificationDiagnostics.reason,
    "short_followup_without_prior_turn_context",
  );
});

// ── Retrieval-triggered memory injection ───────────────────────────────
// Turla alakasız memory fact'lerinin prompt'a hiç enjekte edilmemesi
// pin'leniyor. Bu "gerçekten hatırlama"nın motoru: alakalıysa geç, değilse
// düşür. Pinned/güvenlik fact'leri her modda sağlam kalır.

test("selectMemoryByRelevance: broad mode passes results through when top score is strong", () => {
  const results = [
    { score: 1.5, isPinned: false, importanceScore: 60 },
    { score: 1.0, isPinned: false, importanceScore: 40 },
    { score: 0.4, isPinned: false, importanceScore: 20 },
  ];
  const outcome = selectMemoryByRelevance(results);
  assert.equal(outcome.mode, "broad");
  assert.equal(outcome.results.length, 3);
});

test("selectMemoryByRelevance: surgical mode keeps top-3 plus pinned when score is moderate", () => {
  const results = [
    { score: 0.9, isPinned: false, importanceScore: 40 },
    { score: 0.85, isPinned: false, importanceScore: 40 },
    { score: 0.8, isPinned: false, importanceScore: 40 },
    { score: 0.7, isPinned: true, importanceScore: 20 }, // pinned — sızdırılmalı
    { score: 0.6, isPinned: false, importanceScore: 90 }, // yüksek importance ama pinned değil, düşer
  ];
  assert.ok(MEMORY_RELEVANCE_MODERATE_THRESHOLD < 0.9);
  assert.ok(0.9 < MEMORY_RELEVANCE_STRONG_THRESHOLD);
  const outcome = selectMemoryByRelevance(results);
  assert.equal(outcome.mode, "surgical");
  assert.ok(outcome.results.length <= 4);
  assert.ok(outcome.results.some((r) => r.isPinned), "pinned dropped");
});

test("selectMemoryByRelevance: off mode drops non-pinned low-importance facts", () => {
  const results = [
    { score: 0.5, isPinned: false, importanceScore: 40 }, // alakasız fact
    { score: 0.4, isPinned: false, importanceScore: 30 }, // alakasız fact
    { score: 0.4, isPinned: true, importanceScore: 30 }, // pinned güvenlik faktı — kal
    { score: 0.3, isPinned: false, importanceScore: 92 }, // yüksek importance kimlik — kal
  ];
  const outcome = selectMemoryByRelevance(results);
  assert.equal(outcome.mode, "off");
  // Sadece pinned + high-importance kalmalı
  assert.equal(outcome.results.length, 2);
  assert.ok(outcome.results.every((r) => r.isPinned || (r.importanceScore ?? 0) >= 85));
});

test("selectMemoryByRelevance: empty results yields off mode with empty list", () => {
  const outcome = selectMemoryByRelevance([]);
  assert.equal(outcome.mode, "off");
  assert.equal(outcome.results.length, 0);
});

test("health facts are bucketed by what they measure, not as if every number were a percentage", () => {
  // ÖLÇÜLDÜ (2026-08-26): `qualitativeScore` her büyüklüğü
  // `value > 1 ? value / 100 : value` ile yüzdelik sayıyordu. Sonuç yalnız
  // belirsiz değil TERSTİ — sekiz saat uyku "low", yarım saat "medium",
  // üç yüz adım ile sekiz bin adım ikisi de "high" görünüyordu. Modele
  // kullanıcının sağlığı hakkında aktif olarak yanlış bilgi gidiyordu.
  const now = new Date("2030-01-01T12:00:00.000Z");
  const packetFor = (facts: Record<string, unknown>) =>
    buildContextPacketsFromMetadata(
      {
        chatContext: {
          lastDerivedContextDigest: {
            worldSignals: [
              {
                signalId: "health-buckets",
                kind: "health",
                summary: "Günlük özet hazır.",
                confidence: 0.9,
                createdAt: "2030-01-01T11:30:00.000Z",
                privacy: { backendPlaintextAllowed: true },
                facts,
              },
            ],
          },
        },
      },
      { now },
    )[0]?.summary ?? "";

  assert.match(packetFor({ sleepHoursToday: 8 }), /sleep_h_today=high/);
  assert.match(packetFor({ sleepHoursToday: 6.2 }), /sleep_h_today=medium/);
  assert.match(packetFor({ sleepHoursToday: 4 }), /sleep_h_today=low/);
  assert.match(packetFor({ stepsToday: 8420 }), /steps_today=high/);
  assert.match(packetFor({ stepsToday: 5000 }), /steps_today=medium/);
  assert.match(packetFor({ stepsToday: 300 }), /steps_today=low/);

  // Gerçek 0..1 SKORLARI eskisi gibi kovalanmaya devam eder.
  assert.match(packetFor({ readiness: 0.82 }), /readiness=high/);

  // Ham değer hiçbir koşulda sızmaz.
  for (const raw of ["8420", "6.2", "8 saat"]) {
    assert.doesNotMatch(packetFor({ stepsToday: 8420, sleepHoursToday: 6.2 }), new RegExp(raw));
  }
});

test("a health summary is not delivered mangled by redaction", () => {
  // ÖLÇÜLDÜ (2026-08-26): giren "Bugün 8.420 adım atıldı, 45 dakika aktif."
  // cümlesi modele "Bugün ölçüm atıldı, ölçüm aktif." olarak gidiyordu.
  // Ham ölçümü silmek doğru; ortaya anlamsız bir Türkçe cümle bırakmak
  // değil. Sansür bir şey sildiyse yüksek seviyeli işaret gönderilir ve
  // sayısal ayrıntı zaten izin listesindeki olgulardan nitel olarak geçer.
  const now = new Date("2030-01-01T12:00:00.000Z");
  const summary =
    buildContextPacketsFromMetadata(
      {
        chatContext: {
          lastDerivedContextDigest: {
            worldSignals: [
              {
                signalId: "health-mangled",
                kind: "health",
                summary: "Bugün 8.420 adım atıldı, 45 dakika aktif.",
                confidence: 0.95,
                createdAt: "2030-01-01T11:40:00.000Z",
                privacy: { backendPlaintextAllowed: true },
                facts: { stepsToday: 8420, workoutDurationMinutes: 45 },
              },
            ],
          },
        },
      },
      { now },
    )[0]?.summary ?? "";

  assert.doesNotMatch(summary, /ölçüm atıldı|ölçüm aktif/);
  assert.match(summary, /health_signal=recent/);
  assert.match(summary, /steps_today=high/);
});
