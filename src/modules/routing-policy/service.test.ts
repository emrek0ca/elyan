import assert from "node:assert/strict";
import test from "node:test";
import {
  buildCommandRouteModelPrompt,
  decideCommandRoute,
  resolveCommandTarget,
  resolvePendingDesktopQueueTarget,
} from "./service.js";

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

  groupBy() {
    return this;
  }

  limit() {
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
  constructor(private readonly results: unknown[]) {}

  select() {
    return new FakeQuery(this.results.shift() ?? []);
  }
}

const proSubscriptionRows = [
  [
    {
      planCode: "pro",
      status: "active",
      trialEndsAt: null,
    },
  ],
];

function createApp(
  results: unknown[],
  subscriptionRows: unknown[] = proSubscriptionRows,
  { online = true }: { online?: boolean } = {},
) {
  return {
    db: new FakeDb([...subscriptionRows, ...results]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    // listUserDevices/getUserDevice consult the realtime hub as the
    // authoritative online signal (wsConnected overrides DB heartbeat).
    services: {
      realtimeHub: {
        isRuntimeConnected: () => online,
      },
    },
  };
}

function createDesktopReadyApp(
  capabilities: string[] = [
    "filesystem",
    "document.write",
    "document.read",
    "recent.files",
  ],
) {
  const now = new Date("2030-01-01T00:00:00.000Z");
  return createApp([
    [
      {
        id: "desktop-1",
        type: "desktop",
        externalDeviceId: null,
        label: "User Desktop",
        platform: "macos",
        runtimeVersion: "1.0.0",
        appVersion: null,
        isActive: true,
        pairedAt: now,
        lastSeenAt: now,
        createdAt: now,
        updatedAt: now,
      },
    ],
    [
      {
        id: "runtime-1",
        deviceId: "desktop-1",
        status: "online",
        capabilities,
        capabilityStates: {},
        currentTaskId: null,
        connectedAt: now,
        lastHeartbeatAt: now,
      },
    ],
  ]);
}

test("decideCommandRoute keeps public chat on the shared brain", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Atatürk kimdir?",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.requiresApproval, false);
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.selectedWorkload, "mobile_chat_fast");
  assert.equal(decision.requiredRuntime, "server");
});

test("decideCommandRoute carries one planning contract for compound subject requests", async () => {
  const decision = await decideCommandRoute(createApp([]) as never, {
    userId: "user-1",
    message: "Bu hedef için bir plan oluştur, doktor olmak istiyorum ama matematik bölümündeyim",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.intent, "planning_request");
  assert.equal(decision.selectedWorkload, "planning");
  assert.equal(decision.turnContract?.version, "elyan.turn_contract.v1");
  assert.equal(decision.turnContract?.planIntent, true);
  assert.equal(decision.turnContract?.understandingEnvelope.intent.name, "planning");
  assert.equal(decision.turnContract?.routeDecision.selectedWorkload, "planning");
  assert.equal("message" in (decision.turnContract ?? {}), false);
  assert.equal(
    JSON.stringify(decision.turnContract).includes("doktor olmak istiyorum"),
    false,
  );
});

test("decideCommandRoute keeps a direct math request on the math workload", async () => {
  const decision = await decideCommandRoute(createApp([]) as never, {
    userId: "user-1",
    message: "Bu matematik sorusunu çöz",
    source: "mobile",
  });

  assert.notEqual(decision.intent, "planning_request");
  assert.notEqual(decision.selectedWorkload, "planning");
  assert.equal(decision.turnContract?.planIntent, false);
});

test("decideCommandRoute keeps the objective's ordinary Turkish prompts on chat workloads", async () => {
  const cases = [
    ["Bana anlatır mısın Atatürk'ün gençliğini", "mobile_chat_balanced"],
    ["Fotosentez nasıl çalışır", "mobile_chat_fast"],
    ["Python'da list comprehension nedir", "mobile_chat_fast"],
    ["İyi bir CV nasıl yazılır", "mobile_chat_fast"],
    ["Uykusuzluk neden olur", "mobile_chat_balanced"],
    ["Roma İmparatorluğu neden çöktü", "mobile_chat_balanced"],
    ["Bir fıkra anlat", "mobile_chat_balanced"],
    ["Kuantum dolanıklık nedir", "mobile_chat_fast"],
    ["Evde kahve nasıl demlenir", "mobile_chat_fast"],
    ["Motivasyonumu nasıl artırırım", "mobile_chat_balanced"],
  ] as const;

  for (const [message, expectedWorkload] of cases) {
    const decision = await decideCommandRoute(createApp([]) as never, {
      userId: "user-1",
      message,
      source: "mobile",
      // These are the derived privacy flags added to chat metadata. They are
      // not evidence of an uploaded document and must not escalate the turn.
      metadata: {
        rawFileUploaded: false,
        data_origin: "local_derived",
        privacy_level: "local_derived",
      },
    });

    assert.equal(decision.route, "server_brain", message);
    assert.equal(decision.selectedWorkload, expectedWorkload, message);
    assert.ok(decision.semanticContract, message);
    assert.equal(decision.semanticContract?.conversationMode, "chat", message);
    assert.equal(decision.semanticContract?.surface, "server_brain", message);
    assert.equal(decision.semanticContract?.intent, "answer", message);
    assert.equal(decision.semanticContract?.artifact, "none", message);
    assert.deepEqual(decision.semanticContract?.requiredContext, ["none"], message);
    assert.equal(decision.semanticContract?.sideEffect, "none", message);
    assert.equal(decision.semanticContract?.privacyClass, "public", message);
    assert.equal(decision.semanticContract?.needsApproval, false, message);
    assert.equal(
      new Set([
        "document_analysis",
        "document_generate",
        "public_research",
        "public_deep_research",
        "public_quantum_research",
      ]).has(decision.selectedWorkload),
      false,
      message,
    );
  }
});

test("decideCommandRoute accepts the additive web source without changing routing truth", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Merhaba",
    source: "web",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.requiredRuntime, "server");
});

test("decideCommandRoute sends an explicit remote MCP request to a capable desktop", async () => {
  const app = createDesktopReadyApp(["mcp_call_tool"]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "GitHub repolarımı göster",
    source: "mobile",
    metadata: { desktopDispatch: true },
    selectedDeviceId: "desktop-1",
    requestedCapabilities: ["mcp_call_tool"],
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.privacyClass, "local_private");
  assert.deepEqual(decision.capabilities, ["mcp_call_tool"]);
});

test("decideCommandRoute carries typed semantic desktop dispatch contract from route model", async () => {
  const app = createDesktopReadyApp(["task.execution"]);
  (app.services as Record<string, unknown>).commandRouteModel = {
    decide: async () => ({
      target: "desktop_runtime",
      operationalRoute: "desktop_runtime",
      executionPlan: ["desktop_runtime"],
      reason: "The request needs browser state on the paired desktop.",
      needsDesktop: true,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: [],
      semanticDesktopContract: {
        contract: "elyan.semantic_desktop_dispatch.v1",
        route: "desktop_runtime",
        intent: "browser_workflow",
        requiredSemanticCapabilities: ["browser_control"],
        requiredLocalContext: ["browser"],
        sideEffectLevel: "none",
        confidence: 0.91,
        evidence: ["continue browser workflow"],
      },
    }),
  };

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "devam et ve orada aç",
    source: "mobile",
    selectedDeviceId: "desktop-1",
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(
    decision.taskRoute?.semanticDesktopContract?.contract,
    "elyan.semantic_desktop_dispatch.v1",
  );
  assert.equal(
    decision.taskRoute?.semanticDesktopContract?.intent,
    "browser_workflow",
  );
  assert.deepEqual(
    decision.taskRoute?.semanticDesktopContract?.requiredSemanticCapabilities,
    ["browser_control"],
  );
});

test("decideCommandRoute fails closed when remote MCP runtime is unavailable", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "GitHub repolarımı göster",
    source: "mobile",
    metadata: { desktopDispatch: true },
    requestedCapabilities: ["mcp_call_tool"],
  });

  assert.equal(decision.route, "pairing_required");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.failClosedReason, "remote_mcp_runtime_unavailable");
});

test("decideCommandRoute keeps greetings on the fast shared-brain path", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Selam, nasılsın?",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.shouldAskClarification, false);
  assert.equal(decision.intent, "normal_chat");
  assert.equal(decision.selectedWorkload, "mobile_chat_fast");
});

// RC-6 — Bir cihazın SEÇİLİ olması, turu masaüstü görevine çevirmez. Cihaz
// görevi turun NİYETİNDEN doğmalı, seçili cihazın varlığından değil. Üretim
// vakası: "sadece tek cümleyle söyle: bugün nasılsın" bile seçili cihazla
// tasks satırı açıyordu.
test("decideCommandRoute keeps a conversational turn on the shared brain even with a ready selected desktop", async () => {
  const app = createDesktopReadyApp();
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Selam, nasılsın?",
    source: "mobile",
    selectedDeviceId: "desktop-1",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.notEqual(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute does not turn an imperative-looking chat sentence into a desktop task", async () => {
  const app = createDesktopReadyApp();
  // Rota modeli semantik olarak "bu sohbet" diyor; seçili cihazın varlığı bunu
  // ezmemelidir (karar semantik, kural tabanlı değil).
  (app.services as Record<string, unknown>).commandRouteModel = {
    decide: async () => ({
      target: "server_brain",
      operationalRoute: "server_brain",
      executionPlan: ["server_brain"],
      reason: "The user is just chatting, not asking for real execution.",
      needsDesktop: false,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: [],
      semanticDesktopContract: null,
    }),
  };

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "sadece tek cümleyle söyle: bugün nasılsın?",
    source: "mobile",
    selectedDeviceId: "desktop-1",
  });

  assert.equal(decision.route, "server_brain");
  assert.notEqual(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute selects document_generate for report/document creation prompts", async () => {
  const app = createApp([]);
  for (const message of [
    "Yapay zeka hakkında kısa bir rapor yaz",
    "iklim değişikliği üzerine bir makale hazırla",
    "şirket için bülten hazırlar mısın",
    "yatırım planı için şık bir PDF hazırla",
    "Merhaba dif geo kullanım alanlarıyla alakalı 4 sayfalık PDF yazar mısın",
    "bu konu için tasarımlı bir docx belge oluştur",
  ]) {
    const decision = await decideCommandRoute(app as never, {
      userId: "user-1",
      message,
      source: "mobile",
    });
    assert.equal(decision.route, "server_brain");
    assert.equal(decision.selectedWorkload, "document_generate");
  }
});

test("decideCommandRoute keeps chart and math widget requests on capable server workload", async () => {
  const app = createApp([]);
  for (const message of [
    "f(x)=x^2 fonksiyonunun grafiğini çiz",
    "bu denklemi LaTeX ile adım adım çöz",
    "z = x^3 + y^2 fonksiyonunun 3 boyutlu yüzey grafiğini çiz",
    "4 boyutlu grafik çiz: z = x^3 + y^2",
    "z=f(x,y) çiz surface plot",
  ]) {
    const decision = await decideCommandRoute(app as never, {
      userId: "user-1",
      message,
      source: "mobile",
    });
    assert.equal(decision.route, "server_brain");
    assert.equal(decision.selectedWorkload, "mobile_chat_balanced");
  }
});

test("decideCommandRoute does not select document_generate for read/summary or unrelated prompts", async () => {
  const app = createApp([]);
  for (const message of [
    "raporu özetle",
    "merhaba nasılsın",
    "python ile kod yaz bana",
  ]) {
    const decision = await decideCommandRoute(app as never, {
      userId: "user-1",
      message,
      source: "mobile",
    });
    assert.notEqual(decision.selectedWorkload, "document_generate");
  }
});

test("decideCommandRoute selects table_generate only for explicit table or spreadsheet asks", async () => {
  const app = createApp([]);
  for (const message of [
    "hava durumunu tablo olarak ver",
    "bunu excel tablosu halinde hazirla",
    "ulkeleri csv olarak cikar",
  ]) {
    const decision = await decideCommandRoute(app as never, {
      userId: "user-1",
      message,
      source: "mobile",
    });
    assert.equal(decision.selectedWorkload, "table_generate");
  }
});

test("decideCommandRoute keeps ordinary factual lists out of table_generate", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Turk matematikcileri kisaca anlat",
    source: "mobile",
  });

  assert.notEqual(decision.selectedWorkload, "table_generate");
});

test("decideCommandRoute keeps plan requests out of table_generate", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bana 5 adımlık Teknofest çalışma planı çıkar",
    source: "mobile",
    brainProfile: {
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 5,
      memoryFanout: 6,
      maxTokenScale: 1.25,
    },
  });

  assert.equal(decision.selectedWorkload, "planning");
});

test("decideCommandRoute selects document_generate for suffixed Turkish report requests", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Toplantı notlarından yönetici özeti raporu üret",
    source: "mobile",
  });

  assert.equal(decision.selectedWorkload, "document_generate");
});

test("decideCommandRoute upgrades complex public chat to the balanced profile", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message:
      "iOS canlı etkinlikleri ile normal push bildirimlerini artı eksi yönleriyle karşılaştır ve hangi durumda hangisini tercih etmem gerektiğini kısa ama net açıkla.",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.shouldAskClarification, false);
  // "karşılaştır" triggers research intent → mobile_chat_deep_refine
  assert.equal(decision.selectedWorkload, "mobile_chat_deep_refine");
});

test("decideCommandRoute upgrades complex chat on premium plans to the deep refine profile", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message:
      "iOS canlı etkinlikleri ile normal push bildirimlerini artı eksi yönleriyle karşılaştır, gecikme, görünürlük, etkileşim, pil tüketimi, operatör duyarlılığı ve geri dönüş oranı açısından analiz et, sonra ürün stratejisi için hangi durumda hangisini seçmem gerektiğini kısa bir karar özetiyle anlat.",
    source: "mobile",
    brainProfile: {
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 5,
      memoryFanout: 6,
      maxTokenScale: 1.25,
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.shouldAskClarification, false);
  // "karşılaştır" + "analiz et" triggers research → deep_refine
  assert.equal(decision.selectedWorkload, "mobile_chat_deep_refine");
});

test("decideCommandRoute keeps packaged mobile world context on the shared brain", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message:
      "Bugünkü sağlık, takvim, saat, cihaz durumu ve bildirim bağlamına göre kısa ama tam bir çalışma planı çıkar.",
    source: "mobile",
    brainProfile: {
      tier: "premium",
      reasoningMultiplier: 5,
      retrievalFanout: 5,
      memoryFanout: 6,
      maxTokenScale: 1.25,
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.requiredRuntime, "server");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute routes short Turkish PDF export work to document generation", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bu PDF'i profesyonelce özetle ve düzenli Türkçe ile yaz.",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.shouldAskClarification, false);
  assert.equal(decision.selectedWorkload, "document_generate");
});

test("decideCommandRoute upgrades short follow-ups to balanced so prior turn is used", async () => {
  const app = createApp([]);
  // "anlamadım", "devam et", "onu düzelt" gibi kısa takipler önceki tura
  // referans veriyor; fast modelde bağlamsız yorumlanınca alakasız cevap
  // çıkıyor. Balanced modelde rolling summary + digest bağlamıyla doğru
  // yorumlanıyor.
  for (const message of [
    "anlamadım",
    "devam et",
    "onu düzelt",
    "daha kısa yaz",
  ]) {
    const decision = await decideCommandRoute(app as never, {
      userId: "user-1",
      message,
      source: "mobile",
    });
    assert.equal(decision.selectedWorkload, "mobile_chat_balanced", message);
  }
});

test("decideCommandRoute upgrades compact educational reasoning prompts to balanced", async () => {
  const app = createApp([]);
  for (const message of [
    "Bana bir mat teoremi söyle",
    "Teorem söyle",
    "x^2 türevini al",
    "Bana ileri analiz dersinden örnek soru yaz",
    "Bu fonksiyon neden yanlış sonuç veriyor: `return total / items.length`",
  ]) {
    const decision = await decideCommandRoute(app as never, {
      userId: "user-1",
      message,
      source: "mobile",
    });
    assert.equal(decision.route, "server_brain", message);
    assert.equal(decision.selectedWorkload, "mobile_chat_balanced", message);
  }
});

test("decideCommandRoute sends screen glance requests to desktop analyze_screen", async () => {
  const app = createDesktopReadyApp([
    "runtime.status",
    "analyze_screen",
    "desktop_operator.observe_screen",
  ]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Ekranda ne var?",
    source: "mobile",
    metadata: { desktopDispatch: true },
    requestedCapabilities: ["analyze_screen"],
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.privacyClass, "local_private");
  assert.equal(decision.taskRoute?.operationalRoute, "desktop_runtime");
  assert.equal(
    decision.taskRoute?.requiredCapabilities.includes("analyze_screen"),
    true,
  );
  assert.equal(decision.capabilities.includes("analyze_screen"), true);
});

test("decideCommandRoute does not answer screen glance as normal chat when desktop is missing", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Aktif pencere ne?",
    source: "mobile",
    metadata: { desktopDispatch: true },
    requestedCapabilities: ["analyze_screen"],
  });

  assert.equal(decision.route, "pairing_required");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.failClosedReason, "desktop_runtime_unavailable");
  assert.equal(decision.capabilities.includes("analyze_screen"), true);
});

test("decideCommandRoute still keeps greetings on the fast path even if short", async () => {
  // Kısa takip yükseltmesi selamlaşmaya sızmamalı.
  const app = createApp([]);
  for (const message of ["Selam", "Merhaba", "teşekkürler"]) {
    const decision = await decideCommandRoute(app as never, {
      userId: "user-1",
      message,
      source: "mobile",
    });
    assert.equal(decision.selectedWorkload, "mobile_chat_fast", message);
  }
});

test("decideCommandRoute uses learned quantum quality guard to lift fast chat to balanced", async () => {
  const app = createApp([]);
  const brainProfile = {
    learning: {
      latestQuantumBenchmarkQualified: true,
      latestQuantumLivenessGuardActive: true,
      latestQuantumLivenessGuardTimeoutRisk: "medium",
      latestQuantumLivenessRepairAttemptCount: 1,
    },
    quantum: {
      benchmarkQualified: true,
    },
  };

  const guarded = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Kısa bir ürün fikri ver",
    source: "mobile",
    brainProfile,
  });
  assert.equal(guarded.route, "server_brain");
  assert.equal(guarded.selectedWorkload, "mobile_chat_balanced");
  assert.deepEqual(guarded.qualityGuard, {
    strategy: "quantum_quality_guard_v1",
    source: "runtime_quantum_liveness_feedback",
    applied: true,
    fromWorkload: "mobile_chat_fast",
    toWorkload: "mobile_chat_balanced",
    reason: "quantum_runtime_liveness_repair_signal",
  });

  const greeting = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Merhaba",
    source: "mobile",
    brainProfile,
  });
  assert.equal(greeting.selectedWorkload, "mobile_chat_fast");
  assert.equal(greeting.qualityGuard, undefined);
});

test("decideCommandRoute ignores weak quantum feedback without liveness risk", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Kısa bir ürün fikri ver",
    source: "mobile",
    brainProfile: {
      learning: {
        latestQuantumBenchmarkQualified: true,
        latestQuantumDispatchFeedbackConfidence: 62,
        latestQuantumDispatchPolicyOutcome: "backend_active_no_boost",
        latestQuantumResponsivePolicyOutcome:
          "backend_active_no_responsive_boost",
        latestQuantumLivenessGuardActive: false,
        latestQuantumLivenessGuardTimeoutRisk: "low",
        latestQuantumLivenessRepairAttemptCount: 0,
      },
      quantum: {
        benchmarkQualified: true,
      },
    },
  });

  assert.equal(decision.selectedWorkload, "mobile_chat_fast");
  assert.equal(decision.qualityGuard, undefined);
});

test("decideCommandRoute leaves referential clarification to canonical context", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bunu düzelt",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.shouldAskClarification, false);
  assert.equal(decision.intent, "normal_chat");
  assert.equal(decision.selectedWorkload, "mobile_chat_balanced");
});

test("decideCommandRoute keeps document generation on the shared brain", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bu toplantı notlarını kısa bir PDF özeti olarak hazırla.",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.requiresApproval, false);
  assert.equal(decision.requiredRuntime, "server");
});

test("decideCommandRoute keeps plain text-to-PDF export on the shared brain even with a selected desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Metni PDF olarak ver.",
    source: "mobile",
    selectedDeviceId: "desktop-1",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.requiresApproval, false);
  assert.equal(decision.requiredRuntime, "server");
});

test("decideCommandRoute keeps PDF yap prompts on the shared brain even with a selected desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "PDF yap.",
    source: "mobile",
    selectedDeviceId: "desktop-1",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.requiresApproval, false);
  assert.equal(decision.requiredRuntime, "server");
});

test("decideCommandRoute keeps mobile local export hints on the shared brain even when a desktop target exists", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "İçeriği düzenli hale getir.",
    source: "mobile",
    selectedDeviceId: "desktop-1",
    requestedCapabilities: ["document_write"],
    metadata: {
      documentExportMode: "mobile_local",
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.requiresApproval, false);
  assert.equal(decision.requiredRuntime, "server");
  assert.equal(decision.taskRoute?.needsDesktop, false);
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
});

test("decideCommandRoute keeps attachment export on mobile-local plus shared brain without desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bu belgeyi PDF olarak ver.",
    source: "mobile",
    selectedDeviceId: "desktop-1",
    requestedCapabilities: ["document_write"],
    metadata: {
      documentExportMode: "mobile_local",
      attachments: [
        {
          documentId: "doc-1",
          fileName: "rapor.pdf",
          mimeType: "application/pdf",
          processingState: "deep_ready",
          fastPreview: {
            textPreview: "Rapor içeriği",
            chunks: [{ text: "Rapor içeriği", pageNumber: 1 }],
          },
          raw_file_uploaded: false,
          data_origin: "local_derived",
        },
      ],
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.requiredRuntime, "server");
  assert.equal(decision.taskRoute?.operationalRoute, "server_brain");
  assert.equal(decision.taskRoute?.needsDesktop, false);
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
});

test("decideCommandRoute keeps visual export prompts on the shared brain even with a selected desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Görsel üret.",
    source: "mobile",
    selectedDeviceId: "desktop-1",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.requiresApproval, false);
  assert.equal(decision.requiredRuntime, "server");
});

test("decideCommandRoute keeps compact mobile document reads on the shared brain even with a selected desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bu belgeyi oku ve özetle.",
    source: "mobile",
    selectedDeviceId: "desktop-1",
    requestedCapabilities: ["document_read"],
    metadata: {
      attachments: [
        {
          name: "report.pdf",
          type: "document",
          summary: "Maliyetler, teslimat ve riskler hakkında kısa özet.",
          content:
            "Maliyetler sabit, teslimat iki hafta gecikebilir, riskler düşük.",
          contentLength: 78,
          chunks: [
            {
              text: "Maliyetler sabit, teslimat iki hafta gecikebilir, riskler düşük.",
              pageNumber: 1,
            },
          ],
        },
      ],
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.failClosedReason, null);
  assert.equal(decision.taskRoute?.needsDesktop, false);
  assert.equal(decision.taskRoute?.operationalRoute, "server_brain");
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
});

test("decideCommandRoute keeps local-derived visual analysis on the shared brain even when document_read is requested", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Görseli incele ve ne gördüğünü söyle.",
    source: "mobile",
    selectedDeviceId: "desktop-1",
    requestedCapabilities: ["document_read"],
    metadata: {
      document_analysis: {
        raw_file_uploaded: false,
        data_origin: "local_derived",
        privacy_level: "local_derived",
        extracted_text: "Tabloda gelirler ve giderler listeleniyor.",
        structured_data: {
          pages: [
            {
              pageNumber: 1,
              text: "Tabloda gelirler ve giderler listeleniyor.",
            },
          ],
        },
      },
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.privacyClass, "public_text");
  assert.equal(decision.failClosedReason, null);
  assert.equal(decision.taskRoute?.needsDesktop, false);
  assert.equal(decision.taskRoute?.operationalRoute, "server_brain");
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
});

test("decideCommandRoute keeps structured document envelopes on the shared brain without desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "bu PDF'i özetle",
    source: "mobile",
    selectedDeviceId: "desktop-1",
    metadata: {
      attachments: [
        {
          kind: "document_envelope",
          name: "rapor.pdf",
          mimeType: "application/pdf",
          sourceHash: "sha256:structured-envelope",
          raw_file_uploaded: false,
          data_origin: "local_derived",
          privacy_level: "local_derived",
          documentEnvelope: {
            id: "document-1",
            sourceHash: "sha256:structured-envelope",
            mimeType: "application/pdf",
            blocks: [
              {
                id: "block-1",
                type: "text",
                text: "Maliyetler sabit, teslim tarihi iki hafta gecikebilir.",
                page: 1,
                confidence: 0.94,
                sourceHash: "sha256:structured-envelope",
              },
            ],
          },
        },
      ],
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.taskRoute?.operationalRoute, "server_brain");
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute routes attachment summaries through mobile_local plus shared brain without desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "şu belgeyi özetle",
    source: "mobile",
    metadata: {
      attachments: [
        {
          name: "report.pdf",
          type: "document",
          summary: "Maliyetler, teslimat ve riskler hakkında kısa özet.",
          content:
            "Maliyetler sabit, teslimat iki hafta gecikebilir, riskler düşük.",
          chunks: [
            {
              text: "Maliyetler sabit, teslimat iki hafta gecikebilir, riskler düşük.",
              pageNumber: 1,
            },
          ],
        },
      ],
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.taskRoute?.operationalRoute, "server_brain");
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute treats canonical attachment deepContext as mobile readable", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bu belgeyi özetle",
    source: "mobile",
    metadata: {
      attachments: [
        {
          documentId: "doc-1",
          fileName: "rapor.pdf",
          mimeType: "application/pdf",
          sha256: "abc123",
          processingState: "deep_ready",
          fastPreview: {
            summary: "Rapor bütçe ve teslim tarihini anlatır.",
            textPreview: "Bütçe onayı Haziran sonunda tamamlanacak.",
            chunks: [
              {
                text: "Bütçe onayı Haziran sonunda tamamlanacak.",
                pageNumber: 1,
              },
            ],
          },
          deepContext: {
            document_analysis: {
              documentId: "doc-1",
              summary: "Rapor bütçe ve teslim tarihini anlatır.",
              extractedText: "Bütçe onayı Haziran sonunda tamamlanacak.",
            },
            compactDocument: {
              documentId: "doc-1",
              fileName: "rapor.pdf",
              mimeType: "application/pdf",
              sha256: "abc123",
            },
          },
        },
      ],
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.taskRoute?.operationalRoute, "server_brain");
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute routes PDF important-item extraction through mobile_local plus shared brain without desktop", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "bu PDF’ten önemli maddeleri çıkar",
    source: "mobile",
    metadata: {
      attachments: [
        {
          name: "brief.pdf",
          type: "document",
          summary: "Kısa proje özeti.",
          content:
            "Proje bütçesi sabit, teslim tarihi esnektir, riskler orta düzeydedir.",
          chunks: [
            {
              text: "Proje bütçesi sabit, teslim tarihi esnektir, riskler orta düzeydedir.",
              pageNumber: 1,
            },
          ],
        },
      ],
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.taskRoute?.operationalRoute, "server_brain");
  assert.deepEqual(decision.taskRoute?.executionPlan, ["server_brain"]);
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("resolvePendingDesktopQueueTarget ignores desktops when the plan does not allow desktop access", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = createApp(
    [
      [
        {
          id: "desktop-1",
          type: "desktop",
          externalDeviceId: null,
          label: "User Desktop",
          platform: "macos",
          runtimeVersion: "1.0.0",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [
        {
          id: "runtime-1",
          deviceId: "desktop-1",
          status: "online",
          capabilities: ["runtime.status"],
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
      ],
    ],
    [
      [
        {
          planCode: "free",
          status: "active",
          trialEndsAt: null,
        },
      ],
    ],
  );

  const target = await resolvePendingDesktopQueueTarget(
    app as never,
    "user-1",
    "desktop-1",
    ["web_research"],
  );

  assert.equal(target, null);
});

test("resolvePendingDesktopQueueTarget keeps pairing-required work attached to an offline paired desktop", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = createApp(
    [
      [
        {
          id: "desktop-offline-1",
          type: "desktop",
          externalDeviceId: "elyan-desktop",
          label: "Elyan Desktop",
          platform: "macos",
          runtimeVersion: "1.0.0",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [],
      [],
    ],
    proSubscriptionRows,
    { online: false },
  );

  const target = await resolvePendingDesktopQueueTarget(
    app as never,
    "user-1",
    undefined,
    ["email_send"],
  );

  assert.equal(target?.isSharedBrain, false);
  assert.equal(target?.device.id, "desktop-offline-1");
  assert.equal(target?.device.canReceiveTasks, false);
});

test("decideCommandRoute keeps conceptual quantum chat on the shared brain", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Kuantum dolaşıklık nedir?",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.deepEqual(decision.capabilities, []);
});

test("decideCommandRoute uses public quantum research workload for literature questions", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message:
      "QAOA literatüründe güncel kaynaklarla yaklaşım farklarını araştır.",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.selectedWorkload, "public_quantum_research");
  assert.deepEqual(decision.capabilities, ["web_research"]);
});

test("decideCommandRoute uses deep public research workload for current source-backed reports", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message:
      "2026 AI çip pazarını güncel kaynaklarla kapsamlı rapor olarak araştır.",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.selectedWorkload, "public_deep_research");
});

test("decideCommandRoute keeps private current document prompts off public research workload", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bu özel belgeyi güncel kaynaklarla araştır ve özetle.",
    source: "mobile",
    metadata: {
      attachments: [{ name: "private.pdf", text: "private text" }],
    },
  });

  assert.equal(decision.route, "server_brain");
  assert.notEqual(decision.selectedWorkload, "public_research");
  assert.notEqual(decision.selectedWorkload, "public_deep_research");
});

test("decideCommandRoute carries quantum execution capabilities when dispatch is explicit", async () => {
  const quantumCapabilities = [
    "quantum_model_problem",
    "quantum_run_experiment",
    "quantum_compare_classical",
    "quantum_generate_report",
  ];
  const app = createDesktopReadyApp(quantumCapabilities);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message:
      "Kapasite 5 için QUBO modelle, QAOA çalıştır ve klasik çözümle karşılaştır.",
    source: "mobile",
    metadata: { desktopDispatch: true },
    requestedCapabilities: quantumCapabilities,
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.mode, "executable_task");
  assert.deepEqual(decision.capabilities, quantumCapabilities);
  assert.deepEqual(
    decision.taskRoute?.requiredCapabilities,
    quantumCapabilities,
  );
  assert.equal(decision.taskRoute?.needsDesktop, true);
  assert.equal(decision.privacyClass, "public_text");
});

test("resolveCommandTarget defaults task routing to the first ready desktop", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = {
    db: new FakeDb([
      ...proSubscriptionRows,
      [
        {
          id: "desktop-1",
          type: "desktop",
          externalDeviceId: null,
          label: "User MacBook",
          platform: "macos",
          runtimeVersion: "1.0.0",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [
        {
          id: "runtime-1",
          deviceId: "desktop-1",
          status: "online",
          capabilities: ["filesystem"],
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => true,
      },
    },
  };

  const target = await resolveCommandTarget(
    app as never,
    "user-1",
    undefined,
    "task",
  );

  assert.equal(target.isSharedBrain, false);
  assert.equal(target.device.id, "desktop-1");
});

test("resolveCommandTarget prefers a desktop that matches requested capabilities", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = {
    db: new FakeDb([
      ...proSubscriptionRows,
      [
        {
          id: "desktop-1",
          type: "desktop",
          externalDeviceId: null,
          label: "Basic Desktop",
          platform: "macos",
          runtimeVersion: "1.0.0",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
        {
          id: "desktop-2",
          type: "desktop",
          externalDeviceId: null,
          label: "Automation Desktop",
          platform: "macos",
          runtimeVersion: "1.0.0",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [
        {
          id: "runtime-1",
          deviceId: "desktop-1",
          status: "online",
          capabilities: ["runtime.status"],
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
        {
          id: "runtime-2",
          deviceId: "desktop-2",
          status: "online",
          capabilities: ["runtime.status", "filesystem"],
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => true,
      },
    },
  };

  const target = await resolveCommandTarget(
    app as never,
    "user-1",
    undefined,
    "task",
    ["filesystem"],
  );

  assert.equal(target.isSharedBrain, false);
  assert.equal(target.device.id, "desktop-2");
});

test("resolveCommandTarget fails closed when the explicit desktop target lacks requested capabilities", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = {
    db: new FakeDb([
      ...proSubscriptionRows,
      [
        {
          id: "desktop-1",
          type: "desktop",
          externalDeviceId: null,
          label: "Basic Desktop",
          platform: "macos",
          runtimeVersion: "1.0.0",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [
        {
          id: "runtime-1",
          deviceId: "desktop-1",
          status: "online",
          capabilities: ["runtime.status"],
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => true,
      },
    },
  };

  await assert.rejects(
    () =>
      resolveCommandTarget(app as never, "user-1", "desktop-1", "task", [
        "filesystem",
      ]),
    (error: unknown) => {
      assert.equal(error instanceof Error, true);
      assert.equal(
        (error as { code?: string }).code,
        "runtime_capability_mismatch",
      );
      return true;
    },
  );
});

test("resolveCommandTarget fails closed when the explicit desktop runtime is stale", async () => {
  const now = new Date();
  // Threshold is 5 min and compared with <=, so go clearly past it.
  const staleHeartbeat = new Date(now.getTime() - 6 * 60_000);
  const app = {
    db: new FakeDb([
      ...proSubscriptionRows,
      [
        {
          id: "desktop-1",
          type: "desktop",
          externalDeviceId: null,
          label: "Stale Desktop",
          platform: "macos",
          runtimeVersion: "1.0.0",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [
        {
          id: "runtime-1",
          deviceId: "desktop-1",
          status: "online",
          capabilities: ["runtime.status", "filesystem"],
          currentTaskId: null,
          connectedAt: staleHeartbeat,
          lastHeartbeatAt: staleHeartbeat,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        // Stale heartbeat AND no live WS → runtime is considered stale.
        isRuntimeConnected: () => false,
      },
    },
  };

  await assert.rejects(
    () =>
      resolveCommandTarget(app as never, "user-1", "desktop-1", "task", [
        "filesystem",
      ]),
    (error: unknown) => {
      assert.equal(error instanceof Error, true);
      assert.equal((error as { code?: string }).code, "runtime_unavailable");
      assert.equal(
        (error as { details?: { targetStatus?: string } }).details
          ?.targetStatus,
        "runtime_stale",
      );
      return true;
    },
  );
});

test("resolveCommandTarget keeps chat routing on the shared brain by default", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = {
    db: new FakeDb([
      [
        {
          id: "shared-brain-1",
          type: "desktop",
          externalDeviceId: "shared-brain",
          label: "Elyan",
          platform: "server",
          runtimeVersion: "server",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [
        {
          id: "runtime-1",
          deviceId: "shared-brain-1",
          status: "online",
          capabilities: ["llm"],
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => true,
      },
    },
  };

  const target = await resolveCommandTarget(
    app as never,
    "user-1",
    undefined,
    "chat",
  );

  assert.equal(target.isSharedBrain, true);
  assert.equal(target.device.id, "shared-brain-1");
});

// ---------------------------------------------------------------------------
// User-controlled desktop dispatch (the toggle / one-shot chip).
// Routing is driven ONLY by explicit user intent in metadata — there is no
// keyword/path heuristic any more. These tests lock that contract in place.
// ---------------------------------------------------------------------------

test("decideCommandRoute keeps public chat on the server when dispatch is on", async () => {
  // The laptop toggle stays armed across turns, but a public memory/general-chat
  // question must not become a desktop work order or leak a tool name.
  const app = createDesktopReadyApp();
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "adım ne benim",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.targetDeviceId, undefined);
  assert.equal(decision.mode, "chat");
  assert.equal(decision.requiredRuntime, "server");
  assert.equal(decision.taskRoute?.target, "server_brain");
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute keeps public visual generation on the server when dispatch is on", async () => {
  const app = createDesktopReadyApp(["image_generate"]);
  let routeModelCalls = 0;
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => {
        routeModelCalls += 1;
        throw new Error("public visual generation must not become a desktop task");
      },
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "public-visual-dispatch-user",
    message: "Yeni bir görsel üret kedi resmi olsun",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.requiredRuntime, "server");
  assert.equal(decision.taskRoute?.needsDesktop, false);
  assert.equal(routeModelCalls, 0);
});

test("decideCommandRoute semantically corrects a desktop visual misroute", async () => {
  const app = createDesktopReadyApp(["image_generate"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "desktop_runtime" as const,
        operationalRoute: "desktop_runtime" as const,
        executionPlan: ["desktop_runtime" as const],
        reason: "The model incorrectly treated the public visual request as local work.",
        needsDesktop: true,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "paraphrased-visual-dispatch-user",
    message: "Bana bir kedi çiz",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.targetDeviceId, undefined);
  assert.match(decision.reason, /Public visual output/);
});

test("decideCommandRoute routes desktop action to the desktop when dispatch is on and ready", async () => {
  const app = createDesktopReadyApp(["browser_control"]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Chrome'da yeni sekme aç",
    source: "mobile",
    metadata: { desktopDispatch: true },
    requestedCapabilities: ["browser_control"],
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.mode, "executable_task");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.taskRoute?.target, "desktop_runtime");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute does not let dispatch preference veto an explicit browser action", async () => {
  const app = createDesktopReadyApp(["browser_control"]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Chrome'da yeni sekme aç",
    source: "mobile",
    metadata: { desktopDispatch: false },
    requestedCapabilities: ["browser_control"],
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.mode, "executable_task");
  assert.equal(decision.taskRoute?.target, "desktop_runtime");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute routes a terse local close command with dispatch preference off", async () => {
  const app = createDesktopReadyApp(["close_app"]);
  const decision = await decideCommandRoute(app as never, {
    userId: "local-command-user",
    message: "Chrome u kapat",
    source: "mobile",
    metadata: { desktopDispatch: false },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.turnContract?.understandingConsensus?.targetSurface, "desktop");
});

test("decideCommandRoute ignores legacy routePreference/desktopDispatchOnce signals", async () => {
  // Only desktopDispatch routes. Older/alias signals never reach the desktop —
  // this keeps the contract to a single source of truth.
  const app = createDesktopReadyApp();
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "rapor hazırla",
    source: "mobile",
    metadata: { routePreference: "desktop", desktopDispatchOnce: true },
  });

  assert.equal(decision.route, "server_brain");
});

test("decideCommandRoute routes real local execution even when the old toggle is off", async () => {
  // The route model is the authority now. A real local file action must not be
  // answered as plausible server chat merely because the old toggle is absent.
  const app = createDesktopReadyApp();
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "desktop_runtime" as const,
        operationalRoute: "desktop_runtime" as const,
        executionPlan: ["desktop_runtime" as const],
        reason: "The request requires reading and opening local desktop files.",
        needsDesktop: true,
        needsPrivateDesktopData: true,
        needsUserApproval: false,
        requiredCapabilities: [],
      }),
    },
  });
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "masaüstündeki raporu aç ve özetle",
    source: "mobile",
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.mode, "executable_task");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute honors explicit desktop capabilities from mobile", async () => {
  const app = createDesktopReadyApp(["filesystem_read"]);
  const decision = await decideCommandRoute(app as never, {
    userId: "dispatch-off-capability-user",
    message: "Masaustumdeki raporu oku",
    source: "mobile",
    requestedCapabilities: ["filesystem_read"],
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.mode, "executable_task");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute derives close_app approval from the capability manifest", async () => {
  const app = createDesktopReadyApp(["close_app"]);
  const decision = await decideCommandRoute(app as never, {
    userId: "close-app-approval-route-user",
    message: "Music kapat",
    source: "mobile",
    metadata: { desktopDispatch: true },
    requestedCapabilities: ["close_app"],
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.requiresApproval, true);
  assert.equal(decision.taskRoute?.needsUserApproval, true);
});

test("decideCommandRoute sends explicit runtime tools and skills to the desktop", async () => {
  const requestedCapabilities = [
    "sys_info",
    "retrieve_context",
    "run_skill",
    "desktop_operator.run",
  ];
  const app = createDesktopReadyApp(requestedCapabilities);
  const decision = await decideCommandRoute(app as never, {
    userId: "mobile-tool-skill-user",
    message: "Masaüstü bağlamını ve sistem durumunu kontrol et.",
    source: "mobile",
    requestedCapabilities,
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.mode, "executable_task");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.deepEqual(decision.capabilities, [
    "sys_info",
    "retrieve_context",
    "run_skill",
    "desktop_operator_run",
  ]);
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("battery observation bypasses the route model and compiles to sys_info", async () => {
  let routeModelCalls = 0;
  const app = createDesktopReadyApp(["sys_info"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => {
        routeModelCalls += 1;
        throw new Error("route model must not run for deterministic system observation");
      },
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "battery-observation-user",
    message: "Bilgisayarın şarjı kaç",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(routeModelCalls, 0);
  assert.equal(decision.route, "desktop_runtime");
  assert.deepEqual(decision.capabilities, ["sys_info"]);
  assert.equal(decision.requiresApproval, false);
  assert.deepEqual(decision.taskRoute?.executionSteps, [
    {
      stepId: "step_sys_info",
      device: "desktop",
      capability: "sys_info",
      input: { query: "battery" },
    },
  ]);
  assert.deepEqual(
    decision.taskRoute?.semanticDesktopContract?.requiredSemanticCapabilities,
    ["sys_info"],
  );
});

test("decideCommandRoute uses the model decision for dispatch-enabled execution", async () => {
  const app = createDesktopReadyApp();
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "hybrid" as const,
        operationalRoute: "desktop_runtime" as const,
        executionPlan: ["desktop_runtime" as const],
        reason: "The request requires a private local file.",
        needsDesktop: true,
        needsPrivateDesktopData: true,
        needsUserApproval: false,
        requiredCapabilities: ["filesystem_read"],
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "model-desktop-route-user",
    message: "Son raporumu inceleyip eksikleri soyle",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.deepEqual(decision.capabilities, []);
});

test("command route prompt defines semantic local execution without keyword code", () => {
  const prompt = buildCommandRouteModelPrompt({
    message: "Masaüstü klasörümdekileri listele",
    promptSummary: "Desktop dispatch is available.",
    routeContinuity: "desktop_runtime",
  });

  assert.match(prompt, /Every field below is required/);
  assert.match(prompt, /actual computer state/);
  assert.match(prompt, /asks for advice, not execution/);
  assert.match(prompt, /"target":"desktop_runtime"/);
  assert.match(prompt, /Always return requiredCapabilities as an empty array/);
  assert.match(prompt, /public image/);
  assert.match(prompt, /literal keyword/);
  assert.match(prompt, /Masaüstü klasörümdekileri listele/);
  assert.match(prompt, /previous turn used desktop_runtime/);
  assert.match(prompt, /clear topic change must be routed independently/);
});

test("model route cache is isolated between chat sessions", async () => {
  const app = createApp([]);
  let calls = 0;
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => {
        calls += 1;
        return {
          target: "server_brain" as const,
          operationalRoute: "server_brain" as const,
          executionPlan: ["server_brain" as const],
          reason: "This follow-up remains conversational.",
          needsDesktop: false,
          needsPrivateDesktopData: false,
          needsUserApproval: false,
          requiredCapabilities: [],
        };
      },
    },
  });
  const input = {
    userId: "session-isolated-route-user",
    message: "Onu düzelt",
    source: "mobile" as const,
    metadata: { desktopDispatch: true },
  };

  await decideCommandRoute(app as never, {
    ...input,
    activeChatSessionId: "11111111-1111-4111-8111-111111111111",
    routeContinuity: "server_brain",
  });
  await decideCommandRoute(app as never, {
    ...input,
    activeChatSessionId: "22222222-2222-4222-8222-222222222222",
    routeContinuity: "desktop_runtime",
  });

  assert.equal(calls, 2);
});

test("decideCommandRoute keeps dispatch-enabled conversation on the server when the model does", async () => {
  const app = createDesktopReadyApp();
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain" as const,
        operationalRoute: "server_brain" as const,
        executionPlan: ["server_brain" as const],
        reason: "This is a conversational request.",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "model-chat-route-user",
    message: "Bu gorev icin nasil bir yol izlemeliyim?",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute accepts a schema-valid direct desktop model route", async () => {
  const app = createDesktopReadyApp(["filesystem_read"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "desktop_runtime" as const,
        operationalRoute: "desktop_runtime" as const,
        executionPlan: ["desktop_runtime" as const],
        reason: "The request requires private desktop execution.",
        needsDesktop: true,
        needsPrivateDesktopData: true,
        needsUserApproval: false,
        requiredCapabilities: ["filesystem_read"],
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "direct-model-route-user",
    message: "Yerel raporu incele",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.taskRoute?.target, "desktop_runtime");
});

test("decideCommandRoute sends model-classified local artifact work to desktop", async () => {
  const app = createDesktopReadyApp();
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "desktop_runtime" as const,
        operationalRoute: "desktop_runtime" as const,
        executionPlan: ["desktop_runtime" as const],
        reason: "The user asks Elyan to create a verified local desktop document artifact.",
        needsDesktop: true,
        needsPrivateDesktopData: false,
        needsUserApproval: true,
        requiredCapabilities: [],
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "desktop-artifact-route-user",
    message:
      "Ceza hukuku nedir araştır ve öğrenci için DOCX çalışma rehberini masaüstüne kaydet.",
    source: "mobile",
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.taskRoute?.operationalRoute, "desktop_runtime");
  assert.equal(decision.taskRoute?.needsPrivateDesktopData, false);
  assert.equal(decision.requiresApproval, true);
});

test("decideCommandRoute keeps desktop-word advice on server when model says no execution", async () => {
  const app = createDesktopReadyApp();
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain" as const,
        operationalRoute: "server_brain" as const,
        executionPlan: ["server_brain" as const],
        reason: "The user asks for advice about where to save, not execution.",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "desktop-advice-route-user",
    message: "Raporu masaüstüne kaydetmek iyi fikir mi, nasıl düzenlemeliyim?",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.taskRoute?.needsDesktop, false);
  assert.equal(decision.requiredRuntime, "server");
});

test("decideCommandRoute repairs a valid server model route at the typed local safety boundary", async () => {
  const app = createDesktopReadyApp(["browser_control"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain" as const,
        operationalRoute: "server_brain" as const,
        executionPlan: ["server_brain" as const],
        reason: "The model incorrectly treated this as normal chat.",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "wrong-server-route-desktop-action-user",
    message: "Masaüstümde Chrome uygulamasını aç.",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.taskRoute?.semanticDecision, undefined);
});

test("decideCommandRoute repairs a structured server verdict for an explicit local action", async () => {
  const app = createDesktopReadyApp(["close_app"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain" as const,
        operationalRoute: "server_brain" as const,
        executionPlan: ["server_brain" as const],
        reason: "The model selected conversation for this turn.",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
        semanticDecision: {
          contract: "elyan.agent_route_decision.v1" as const,
          intent: "conversation",
          targetDevice: "control-plane" as const,
          goalContract: {
            successCriteria: ["response_generated"],
          },
          requiredCapabilities: [],
          steps: [],
          verification: {
            required: false,
            criteria: ["response_generated"],
          },
          confidence: 0.96,
          missingInformation: [],
          requiresConfirmation: false,
        },
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "structured-server-route-user",
    message: "Music kapat",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.taskRoute?.semanticDecision, undefined);
});

test("decideCommandRoute carries a structured desktop plan and approval decision", async () => {
  const app = createDesktopReadyApp(["close_app"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "desktop_runtime" as const,
        operationalRoute: "desktop_runtime" as const,
        executionPlan: ["desktop_runtime" as const],
        reason: "The request changes the paired desktop app state.",
        needsDesktop: true,
        needsPrivateDesktopData: true,
        needsUserApproval: true,
        requiredCapabilities: [],
        semanticDecision: {
          contract: "elyan.agent_route_decision.v1" as const,
          intent: "close_app",
          targetDevice: "desktop" as const,
          goalContract: {
            successCriteria: ["music_process_absent"],
          },
          requiredCapabilities: ["close_app"],
          steps: [
            {
              stepId: "close_music",
              device: "desktop" as const,
              capability: "close_app",
            },
          ],
          verification: {
            required: true,
            criteria: ["process_readback"],
          },
          confidence: 0.95,
          missingInformation: [],
          requiresConfirmation: true,
        },
        semanticDesktopContract: {
          route: "desktop_runtime" as const,
          intent: "screen_action" as const,
          requiredSemanticCapabilities: ["close_app"],
          requiredLocalContext: ["app"],
          sideEffectLevel: "destructive" as const,
          confidence: 0.95,
          evidence: ["close the selected app"],
        },
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "structured-desktop-route-user",
    message: "Music kapat",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.requiresApproval, true);
  assert.deepEqual(
    decision.taskRoute?.executionSteps,
    [{ stepId: "close_music", device: "desktop", capability: "close_app" }],
  );
  assert.equal(
    decision.taskRoute?.semanticDecision?.verification.required,
    true,
  );
});

test("decideCommandRoute asks only the structured missing-field question", async () => {
  const app = createApp([]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain" as const,
        operationalRoute: "server_brain" as const,
        executionPlan: ["server_brain" as const],
        reason: "A target file is required.",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
        semanticDecision: {
          contract: "elyan.agent_route_decision.v1" as const,
          intent: "edit_document",
          targetDevice: "control-plane" as const,
          goalContract: { successCriteria: ["document_updated"] },
          requiredCapabilities: [],
          steps: [],
          verification: { required: false, criteria: ["response_generated"] },
          confidence: 0.91,
          missingInformation: ["Hangi dosyayı düzenleyeyim?"],
          requiresConfirmation: false,
        },
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "typed-missing-field-user",
    message: "Bunu düzenle",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.shouldAskClarification, true);
  assert.equal(decision.userFacingMessage, "Hangi dosyayı düzenleyeyim?");
});

test("decideCommandRoute treats low model confidence as internal fallback", async () => {
  const app = createApp([]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain" as const,
        operationalRoute: "server_brain" as const,
        executionPlan: ["server_brain" as const],
        reason: "Low-confidence conversation route.",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
        semanticDecision: {
          contract: "elyan.agent_route_decision.v1" as const,
          intent: "conversation",
          targetDevice: "control-plane" as const,
          goalContract: { successCriteria: ["response_generated"] },
          requiredCapabilities: [],
          steps: [],
          verification: { required: false, criteria: ["response_generated"] },
          confidence: 0.4,
          missingInformation: [],
          requiresConfirmation: false,
        },
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "low-confidence-route-user",
    message: "Kısa bir öneri ver",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.shouldAskClarification, false);
});

test("decideCommandRoute keeps a model desktop plan paired-required when offline", async () => {
  const app = createApp([]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "desktop_runtime" as const,
        operationalRoute: "desktop_runtime" as const,
        executionPlan: ["desktop_runtime" as const],
        reason: "The request needs the user's computer.",
        needsDesktop: true,
        needsPrivateDesktopData: true,
        needsUserApproval: false,
        requiredCapabilities: [],
        semanticDecision: {
          contract: "elyan.agent_route_decision.v1" as const,
          intent: "inspect_app",
          targetDevice: "desktop" as const,
          goalContract: { successCriteria: ["state_readback"] },
          requiredCapabilities: ["process_list"],
          steps: [
            { stepId: "observe", device: "desktop" as const, capability: "process_list" },
          ],
          verification: { required: true, criteria: ["state_readback"] },
          confidence: 0.94,
          missingInformation: [],
          requiresConfirmation: false,
        },
        semanticDesktopContract: {
          route: "desktop_runtime" as const,
          intent: "screen_action" as const,
          requiredSemanticCapabilities: ["process_list"],
          requiredLocalContext: ["app"],
          sideEffectLevel: "read" as const,
          confidence: 0.94,
          evidence: ["inspect the app state"],
        },
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "offline-model-desktop-user",
    message: "Music açık mı?",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "pairing_required");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.taskRoute?.semanticDecision?.targetDevice, "desktop");
});

test("decideCommandRoute rejects string booleans from a malformed model route", async () => {
  const app = createDesktopReadyApp(["filesystem_read"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () =>
        ({
          target: "desktop_runtime",
          operationalRoute: "desktop_runtime",
          executionPlan: ["desktop_runtime"],
          reason: "Malformed boolean fields.",
          needsDesktop: "true",
          needsPrivateDesktopData: "true",
          needsUserApproval: "false",
          requiredCapabilities: ["filesystem_read"],
        }) as never,
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "malformed-model-route-user",
    message: "Yerel raporu incele",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.targetDeviceId, undefined);
});

test("decideCommandRoute uses regex fallback only when route model fails technically", async () => {
  const app = createDesktopReadyApp(["filesystem_read"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => {
        throw new Error("route model timeout");
      },
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "route-model-timeout-fallback-user",
    message: "Masaüstümdeki dosyaları listele",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.match(
    decision.taskRoute?.semanticDesktopContract?.evidence.join("\n") ?? "",
    /model_error/,
  );
});

test("decideCommandRoute maps a latest desktop report lookup to file_find", async () => {
  const app = createDesktopReadyApp(["file_find"]);
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => {
        throw new Error("route model timeout");
      },
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "latest-desktop-report-user",
    message: "masaüstündeki son raporu bul ve telefonuma gönder",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.taskRoute?.semanticDesktopContract?.intent, "file_workflow");
  assert.deepEqual(
    decision.taskRoute?.semanticDesktopContract?.requiredSemanticCapabilities,
    ["file_find"],
  );
  assert.deepEqual(
    decision.taskRoute?.semanticDesktopContract?.requiredLocalContext,
    ["filesystem"],
  );
});

test("decideCommandRoute fails closed when an explicit desktop capability has no runtime", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "masaüstümdeki dosyaları aç",
    source: "mobile",
    metadata: { desktopDispatch: true },
    requestedCapabilities: ["filesystem_read"],
  });

  assert.equal(decision.route, "pairing_required");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.failClosedReason, "desktop_runtime_unavailable");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute fails closed when desktop execution is required but plan forbids desktop", async () => {
  const app = createDesktopReadyApp();
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "masaüstümdeki dosyaları aç",
    source: "mobile",
    desktopAllowed: false,
    metadata: { desktopDispatch: true },
    requestedCapabilities: ["filesystem_read"],
  });

  assert.equal(decision.route, "unavailable");
  assert.equal(decision.failClosedReason, "desktop_plan_required");
  assert.equal(decision.requiredRuntime, "desktop");
});

test("decideCommandRoute does not reinterpret low-confidence text as clarification", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "bunu düzelt",
    source: "mobile",
  });

  assert.equal(decision.intent, "normal_chat");
  assert.equal(decision.shouldAskClarification, false);
  assert.equal(decision.selectedWorkload, "mobile_chat_balanced");
});

test("decideCommandRoute keeps confident simple questions on the fast profile", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Atatürk kimdir?",
    source: "mobile",
  });

  assert.equal(decision.intent, "normal_chat");
  assert.equal(decision.selectedWorkload, "mobile_chat_fast");
});

test("decideCommandRoute skips the network route model for semantic server-only chat", async () => {
  const app = createApp([]);
  let routeModelCalls = 0;
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => {
        routeModelCalls += 1;
        throw new Error("server-only chat must not consult the route model");
      },
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Atatürk kimdir?",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(routeModelCalls, 0);
});

// Canlı arıza (2026-08-07): "Chromeu kapat" — apaçık masaüstü komutu —
// sınıflandırıcının "bilmiyorum" kovasına (chat/0.55) düşüyor, mobil
// selectedDeviceId göndermiyor ve regex çiti bu yazımı tanımıyordu; semantik
// router hiç çağrılmadan tur sohbete gidiyordu. Kullanıcının CANLI masaüstü
// çalışma zamanı varken belirsiz tur mutlaka modele sorulmalı.
test("decideCommandRoute consults the route model for an ambiguous turn when a live desktop runtime exists", async () => {
  const app = createApp([]);
  let consulted = 0;
  Object.assign(app.services, {
    realtimeHub: {
      isRuntimeConnected: () => true,
      hasConnectedRuntimeForUser: () => true,
    },
    commandRouteModel: {
      decide: async () => {
        consulted += 1;
        return {
          target: "server_brain",
          operationalRoute: "server_brain",
          executionPlan: ["server_brain"],
          reason: "test",
          needsDesktop: false,
          needsPrivateDesktopData: false,
          needsUserApproval: false,
          requiredCapabilities: [],
          semanticDesktopContract: null,
        };
      },
    },
  });

  await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Chromeu kapat",
    source: "mobile",
  });

  assert.equal(consulted, 1);
});

test("decideCommandRoute still skips the route model when no desktop runtime is live", async () => {
  const app = createApp([]);
  let consulted = 0;
  Object.assign(app.services, {
    realtimeHub: {
      isRuntimeConnected: () => false,
      hasConnectedRuntimeForUser: () => false,
    },
    commandRouteModel: {
      decide: async () => {
        consulted += 1;
        throw new Error("must not consult without a live desktop");
      },
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Atatürk kimdir?",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(consulted, 0);
});

test("decideCommandRoute repairs the model server route when classifier needs local runtime", async () => {
  const app = createDesktopReadyApp(["make_directory", "file_write"]);
  Object.assign(app.services, {
    realtimeHub: {
      isRuntimeConnected: () => true,
      hasConnectedRuntimeForUser: () => true,
    },
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain",
        operationalRoute: "server_brain",
        executionPlan: ["server_brain"],
        reason: "model wrongly classified an explicit local action as chat",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
        semanticDesktopContract: null,
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Masaüstünde Emre adında klasör oluştur",
    source: "mobile",
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute keeps a plain chat turn on the server brain even with a live desktop", async () => {
  const app = createApp([]);
  Object.assign(app.services, {
    realtimeHub: {
      isRuntimeConnected: () => true,
      hasConnectedRuntimeForUser: () => true,
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Atatürk kimdir?",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
});

// Canlı üretim ölçümü (2026-08-08, gerçek kodla backend container'ında):
//   CLS        intent=computer, requiresLocalRuntime=true  (tur doğru anlaşıldı)
//   DEV        masaüstü online=true, canReceiveTasks=true  (cihaz hazır)
//   ROUTEMODEL false                                       (semantik router YOK)
// Rota modeli üretimde yapılandırılmadığı için masaüstüne giden tek yol regex
// çitiydi ve o da bu cümleyi tanımıyordu → görev sohbete düştü. Router karar
// üretemediğinde sınıflandırıcının verdisi + hazır cihaz yeterli olmalı.
test("decideCommandRoute routes to desktop when the route model cannot decide but the classifier needs local runtime", async () => {
  // Üretimdeki gerçek durum: `commandRouteModel` servisi HİÇ yok.
  const app = createDesktopReadyApp();

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Masaüstünde Cabir adında klasör oluştur",
    source: "mobile",
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

test("decideCommandRoute does not let an explicit server verdict suppress a local task", async () => {
  const app = createDesktopReadyApp();
  Object.assign(app.services, {
    commandRouteModel: {
      decide: async () => ({
        target: "server_brain",
        operationalRoute: "server_brain",
        executionPlan: ["server_brain"],
        reason: "model wrongly treated a local action as chat",
        needsDesktop: false,
        needsPrivateDesktopData: false,
        needsUserApproval: false,
        requiredCapabilities: [],
        semanticDesktopContract: null,
      }),
    },
  });

  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Masaüstünde Cabir adında klasör oluştur",
    source: "mobile",
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.taskRoute?.needsDesktop, true);
});

// ---------------------------------------------------------------------------
// A chat session persists its execution target. For ordinary conversation that
// stored target is the SHARED BRAIN device (userId null). Live regression
// (2026-08-21): a later turn in the same session routed to the desktop, the
// stored shared-brain id arrived as the desktop "preference", and the whole
// dispatch died with 422 `invalid_target` — the user saw "Target device is not
// a valid desktop runtime" while their MacBook was online with 102
// capabilities. Shared brain is not a desktop target, but it is not a client
// error either: drop it as a preference and select the desktop normally.
// ---------------------------------------------------------------------------
test("resolveCommandTarget falls back to the live desktop when a chat session hands it the shared-brain target", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const sharedBrainRow = {
    id: "shared-brain-1",
    type: "desktop",
    externalDeviceId: "shared-brain",
    label: "Elyan",
    platform: "server",
    runtimeVersion: "server",
    appVersion: null,
    isActive: true,
    pairedAt: now,
    lastSeenAt: now,
    createdAt: now,
    updatedAt: now,
  };
  const desktopRow = {
    id: "desktop-1",
    type: "desktop",
    externalDeviceId: "mac-1",
    label: "User MacBook",
    platform: "macos",
    runtimeVersion: "1.0.0",
    appVersion: null,
    isActive: true,
    pairedAt: now,
    lastSeenAt: now,
    createdAt: now,
    updatedAt: now,
  };
  const app = {
    db: new FakeDb([
      // getUserDevice(shared-brain-1): usage truth, then the owned-device
      // lookup that finds nothing because the shared brain has no owner.
      ...proSubscriptionRows,
      [],
      // getSharedBrainTargetDevice(): the device row, then its runtime row.
      [sharedBrainRow],
      [],
      // getDefaultDesktopTaskTarget() -> listUserDevices().
      ...proSubscriptionRows,
      [desktopRow],
      [
        {
          id: "runtime-1",
          deviceId: "desktop-1",
          status: "online",
          capabilities: ["filesystem"],
          capabilityStates: {},
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
      ],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => true,
      },
    },
  };

  const target = await resolveCommandTarget(
    app as never,
    "user-1",
    "shared-brain-1",
    "task",
  );

  assert.equal(target.isSharedBrain, false);
  assert.equal(target.device.id, "desktop-1");
});

test("resolveCommandTarget still rejects a target device the user does not own", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = {
    db: new FakeDb([
      ...proSubscriptionRows,
      [],
      [
        {
          id: "shared-brain-1",
          type: "desktop",
          externalDeviceId: "shared-brain",
          label: "Elyan",
          platform: "server",
          runtimeVersion: "server",
          appVersion: null,
          isActive: true,
          pairedAt: now,
          lastSeenAt: now,
          createdAt: now,
          updatedAt: now,
        },
      ],
      [],
    ]),
    config: {
      APP_BASE_URL: "https://api.elyan.dev",
    },
    services: {
      realtimeHub: {
        isRuntimeConnected: () => true,
      },
    },
  };

  await assert.rejects(
    () =>
      resolveCommandTarget(
        app as never,
        "user-1",
        "someone-elses-desktop",
        "task",
      ),
    (error: unknown) =>
      (error as { code?: string }).code === "invalid_target",
  );
});
