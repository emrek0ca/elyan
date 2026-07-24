import assert from "node:assert/strict";
import test from "node:test";
import { decideCommandRoute, resolveCommandTarget, resolvePendingDesktopQueueTarget } from "./service.js";

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

function createDesktopReadyApp(capabilities: string[] = ["filesystem", "document.write", "document.read", "recent.files"]) {
  const now = new Date("2030-01-01T00:00:00.000Z");
  return createApp(
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
          capabilities,
          capabilityStates: {},
          currentTaskId: null,
          connectedAt: now,
          lastHeartbeatAt: now,
        },
      ],
    ],
  );
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
    selectedDeviceId: "desktop-1",
    requestedCapabilities: ["mcp_call_tool"],
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.privacyClass, "local_private");
  assert.deepEqual(decision.capabilities, ["mcp_call_tool"]);
});

test("decideCommandRoute fails closed when remote MCP runtime is unavailable", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "GitHub repolarımı göster",
    source: "mobile",
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
  for (const message of ["anlamadım", "devam et", "onu düzelt", "daha kısa yaz"]) {
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
  for (const message of ["Bana bir mat teoremi söyle", "Teorem söyle", "x^2 türevini al"]) {
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
  const app = createDesktopReadyApp(["runtime.status", "analyze_screen", "desktop_operator.observe_screen"]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Ekranda ne var?",
    source: "mobile",
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.privacyClass, "local_private");
  assert.equal(decision.taskRoute?.operationalRoute, "desktop_runtime");
  assert.equal(decision.taskRoute?.requiredCapabilities.includes("analyze_screen"), true);
  assert.equal(decision.capabilities.includes("analyze_screen"), true);
});

test("decideCommandRoute does not answer screen glance as normal chat when desktop is missing", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Aktif pencere ne?",
    source: "mobile",
  });

  assert.equal(decision.route, "pairing_required");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.failClosedReason, "desktop_screen_context_unavailable");
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
        latestQuantumResponsivePolicyOutcome: "backend_active_no_responsive_boost",
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

test("decideCommandRoute keeps vague referential prompts in clarification mode", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Bunu düzelt",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.shouldAskClarification, true);
  assert.equal(decision.intent, "ambiguous_request");
  // Belirsiz intent artık fast'ta bırakılmıyor: bir kademe yukarı (balanced)
  // çıkar ki önceki tur bağlamıyla doğru yorumlanabilsin.
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
          content: "Maliyetler sabit, teslimat iki hafta gecikebilir, riskler düşük.",
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
          content: "Maliyetler sabit, teslimat iki hafta gecikebilir, riskler düşük.",
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
          content: "Proje bütçesi sabit, teslim tarihi esnektir, riskler orta düzeydedir.",
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
  const app = createApp([
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
  ], [
    [
      {
        planCode: "free",
        status: "active",
        trialEndsAt: null,
      },
    ],
  ]);

  const target = await resolvePendingDesktopQueueTarget(app as never, "user-1", "desktop-1", ["web_research"]);

  assert.equal(target, null);
});

test("resolvePendingDesktopQueueTarget keeps pairing-required work attached to an offline paired desktop", async () => {
  const now = new Date("2030-01-01T00:00:00.000Z");
  const app = createApp([
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
  ], proSubscriptionRows, { online: false });

  const target = await resolvePendingDesktopQueueTarget(app as never, "user-1", undefined, [
    "email_send",
  ]);

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
    message: "Kapasite 5 için QUBO modelle, QAOA çalıştır ve klasik çözümle karşılaştır.",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.mode, "executable_task");
  assert.deepEqual(decision.capabilities, quantumCapabilities);
  assert.deepEqual(decision.taskRoute?.requiredCapabilities, quantumCapabilities);
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

  const target = await resolveCommandTarget(app as never, "user-1", undefined, "task");

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

  const target = await resolveCommandTarget(app as never, "user-1", undefined, "task", ["filesystem"]);

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
    () => resolveCommandTarget(app as never, "user-1", "desktop-1", "task", ["filesystem"]),
    (error: unknown) => {
      assert.equal(error instanceof Error, true);
      assert.equal((error as { code?: string }).code, "runtime_capability_mismatch");
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
    () => resolveCommandTarget(app as never, "user-1", "desktop-1", "task", ["filesystem"]),
    (error: unknown) => {
      assert.equal(error instanceof Error, true);
      assert.equal((error as { code?: string }).code, "runtime_unavailable");
      assert.equal((error as { details?: { targetStatus?: string } }).details?.targetStatus, "runtime_stale");
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

  const target = await resolveCommandTarget(app as never, "user-1", undefined, "chat");

  assert.equal(target.isSharedBrain, true);
  assert.equal(target.device.id, "shared-brain-1");
});

// ---------------------------------------------------------------------------
// User-controlled desktop dispatch (the toggle / one-shot chip).
// Routing is driven ONLY by explicit user intent in metadata — there is no
// keyword/path heuristic any more. These tests lock that contract in place.
// ---------------------------------------------------------------------------

test("decideCommandRoute routes to the desktop when dispatch is on and a desktop is ready", async () => {
  // The laptop toggle is explicit cowork dispatch. When a ready desktop exists,
  // the backend hands the chat turn to the desktop instead of re-running local
  // keyword heuristics.
  const app = createDesktopReadyApp();
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "Fransa'nın başkenti neresidir?",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "desktop_runtime");
  assert.equal(decision.targetDeviceId, "desktop-1");
  assert.equal(decision.mode, "executable_task");
  assert.equal(decision.requiredRuntime, "desktop");
  assert.equal(decision.taskRoute?.target, "desktop_runtime");
  assert.equal(decision.taskRoute?.needsDesktop, true);
  assert.equal(decision.intent, "desktop_cowork");
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

test("decideCommandRoute keeps everything on the shared brain when the toggle is off", async () => {
  // Even an unmistakably desktop-sounding prompt with a ready desktop stays on
  // the server brain unless the user explicitly opts in. No silent auto-routing.
  const app = createDesktopReadyApp();
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "masaüstündeki raporu aç ve özetle",
    source: "mobile",
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.mode, "chat");
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute keeps chat on the server when dispatch is on but no desktop is ready", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "masaüstümdeki dosyaları aç",
    source: "mobile",
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.requiredRuntime, "server");
  assert.equal(decision.failClosedReason, null);
  assert.equal(decision.taskRoute?.needsDesktop, false);
});

test("decideCommandRoute keeps chat on the server when dispatch is on but the plan forbids desktop", async () => {
  const app = createDesktopReadyApp();
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "masaüstümdeki dosyaları aç",
    source: "mobile",
    desktopAllowed: false,
    metadata: { desktopDispatch: true },
  });

  assert.equal(decision.route, "server_brain");
  assert.equal(decision.failClosedReason, null);
  assert.equal(
    decision.userFacingMessage,
    "Masaüstü bağlantısı bu planda kapalı; sohbet burada devam ediyor.",
  );
});

test("decideCommandRoute escalates low-confidence ambiguous prompts to the balanced profile", async () => {
  const app = createApp([]);
  const decision = await decideCommandRoute(app as never, {
    userId: "user-1",
    message: "bunu düzelt",
    source: "mobile",
  });

  assert.equal(decision.intent, "ambiguous_request");
  assert.equal(decision.shouldAskClarification, true);
  // Belirsiz kısa referans fast modele düşmemeli: balanced, önceki tur
  // bağlamını (rolling summary + digest) taşıyabilen kademe.
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
