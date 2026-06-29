import assert from "node:assert/strict";
import test from "node:test";
import { classifyIntent } from "./intent-classifier.js";
import { buildUserContextFromMemory, selectContinuityMemory } from "./context-builder.js";
import { buildContextPacketsFromMetadata } from "./context-packets.js";

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

test("buildUserContextFromMemory promotes derived world-signal memory into situational and behavioral hints", () => {
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

  assert.ok(context.situationalHints.some((hint) => hint.includes("low energy window")));
  assert.ok(context.behavioralHints.some((hint) => hint.includes("compact time-boxed")));
  assert.equal(context.memorySnapshot?.derivedFacts.length, 2);
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
        compactContext: {
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
        compactContext: {
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
  assert.match(packets[0]?.summary ?? "", /hazırlık: yüksek/);
  assert.match(packets[0]?.summary ?? "", /stres: orta/);
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
  assert.match(packets.find((packet) => packet.kind === "calendar_context")?.summary ?? "", /toplantı yükü: orta/);
  assert.match(packets.find((packet) => packet.kind === "device_context")?.summary ?? "", /pil: düşük/);
  assert.match(packets.find((packet) => packet.kind === "notification_context")?.summary ?? "", /Bildirim yoğunluğu güvenli özet/);
  assert.match(packets.find((packet) => packet.kind === "time_context")?.summary ?? "", /saat dilimi: Europe\/Istanbul/);
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

  assert.equal(packets.length, 3);
  assert.deepEqual(
    packets.map((packet) => packet.mentionPolicy),
    ["silent", "silent", "silent"],
  );
  assert.ok(packets.every((packet) => packet.relevanceReason === "greeting_context_suppressed"));
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
            facts: { energy: "orta", sleepQuality: "düşük" },
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
  };

  const devicePackets = buildContextPacketsFromMetadata(baseSignals, {
    now,
    requestText: "Pil durumum sohbeti etkiler mi?",
    intent: "chat",
  });
  assert.equal(devicePackets.find((packet) => packet.kind === "device_context")?.mentionPolicy, "explicit_when_relevant");
  assert.equal(devicePackets.find((packet) => packet.kind === "health_context")?.mentionPolicy, "silent");

  const planningPackets = buildContextPacketsFromMetadata(baseSignals, {
    now,
    requestText: "Bugün çalışma planı çıkar.",
    intent: "planning",
  });
  assert.equal(planningPackets.find((packet) => packet.kind === "health_context")?.mentionPolicy, "implicit");

  const localPackets = buildContextPacketsFromMetadata(baseSignals, {
    now,
    requestText: "Kayseri civarında yemek öner.",
    intent: "chat",
  });
  assert.equal(localPackets.find((packet) => packet.kind === "world_context")?.mentionPolicy, "explicit_when_relevant");
  assert.match(localPackets.find((packet) => packet.kind === "world_context")?.summary ?? "", /şehir: Kayseri/);
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
