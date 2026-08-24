import assert from "node:assert/strict";
import test from "node:test";
import { buildTaskTraceBlock, enrichTaskTraceWithAgentPlan } from "./task-trace.js";

test("buildTaskTraceBlock adds human-readable phase metadata", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-1",
      status: "completed",
      payload: {
        metadata: {
          understanding: {
            intent: {
              primaryIntent: "chat",
            },
          },
        },
      },
      result: {
        brain: {
          qualityPolicyApplied: true,
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Hazır.",
  });

  assert.equal(block.progressLabel, "Yanıt hazır");
  assert.equal(block.phase, "response");
  assert.equal(block.summary, "Kontrol tamam.");
  assert.equal(block.activeStepId, undefined);
});

test("buildTaskTraceBlock hides ordinary chat route rationale from the card trigger", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-route-rationale",
      status: "completed",
      payload: {
        metadata: {
          routeDecision: {
            route: "server_brain",
            userFacingMessage: "Bu istek sohbet olarak işlenecek.",
            taskRoute: {
              target: "server_brain",
              operationalRoute: "server_brain",
              needsDesktop: false,
              needsPrivateDesktopData: false,
            },
          },
        },
      },
      createdAt: new Date("2026-07-19T09:00:00.000Z"),
      updatedAt: new Date("2026-07-19T09:00:01.000Z"),
      completedAt: new Date("2026-07-19T09:00:01.000Z"),
    },
    assistantContent: "Hazır.",
  });

  assert.equal(block.routeReason, undefined);
  assert.equal(
    block.steps.find((step) => step.id === "route")?.detail,
    "Yanıt yolu seçildi.",
  );
});

test("buildTaskTraceBlock reads web and RAG evidence from a durable flat task result", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-research-pdf",
      status: "completed",
      payload: {},
      result: {
        webGroundingUsed: true,
        webSourceCount: 4,
        retrievalResultCount: 3,
      },
      createdAt: new Date("2026-07-19T09:00:00.000Z"),
      updatedAt: new Date("2026-07-19T09:00:04.000Z"),
      completedAt: new Date("2026-07-19T09:00:04.000Z"),
    },
    assistantContent: "Araştırma raporu hazır.",
  });

  const contextStep = block.steps.find((step) => step.id === "context");
  assert.equal(contextStep?.status, "completed");
  assert.equal(contextStep?.detail, "Belge bağlamı hazır.");
});

test("buildTaskTraceBlock explains an explicitly selected desktop mode", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-desktop-mode",
      status: "completed",
      payload: {
        metadata: {
          routeDecision: {
            route: "desktop_runtime",
            userFacingMessage: "Bu görev masaüstünde çalışacak.",
            taskRoute: {
              target: "desktop_runtime",
              operationalRoute: "desktop_runtime",
              needsDesktop: true,
              needsPrivateDesktopData: false,
            },
          },
        },
      },
    },
    assistantContent: "Hazır.",
  });

  assert.equal(
    block.routeReason,
    "Elyan bunu masaüstünde çalıştırdı çünkü masaüstü çalışma modu seçildi.",
  );
});

test("buildTaskTraceBlock never claims an unavailable desktop ran", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-pairing-required",
      status: "waiting_approval",
      payload: {
        metadata: {
          routeDecision: {
            route: "pairing_required",
            userFacingMessage: "Bu görev için hazır bir masaüstü bulunamadı.",
            taskRoute: {
              target: "desktop_runtime",
              operationalRoute: "desktop_runtime",
              needsDesktop: true,
              needsPrivateDesktopData: true,
            },
          },
        },
      },
    },
    assistantContent: "",
  });

  assert.equal(
    block.routeReason,
    "Bu görev için hazır bir masaüstü bulunamadı.",
  );
  assert.doesNotMatch(block.routeReason ?? "", /çalıştırdı/i);
});

test("buildTaskTraceBlock never exposes protected internal route metadata", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-safe-route-rationale",
      status: "completed",
      payload: {
        metadata: {
          routeDecision: {
            route: "desktop_runtime",
            reason: "OpenAI internal routing selected GPT.",
            userFacingMessage: "OpenAI internal routing selected GPT.",
            taskRoute: {
              target: "desktop_runtime",
              operationalRoute: "desktop_runtime",
              needsDesktop: true,
              needsPrivateDesktopData: true,
            },
          },
        },
      },
    },
    assistantContent: "Hazır.",
  });

  assert.equal(
    block.routeReason,
    "Elyan bunu masaüstünde çalıştırdı çünkü görev özel yerel veri veya bilgisayar erişimi gerektiriyor.",
  );
  assert.doesNotMatch(JSON.stringify(block), /openai|gpt|internal routing/i);
});

test("buildTaskTraceBlock keeps a pending desktop plan visibly pending", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-pending-desktop-plan",
      status: "queued",
      payload: {
        metadata: {
          routeDecision: {
            route: "desktop_runtime",
            taskRoute: {
              target: "desktop_runtime",
              operationalRoute: "desktop_runtime",
              needsDesktop: true,
              executionPlan: ["desktop_runtime"],
            },
          },
        },
        desktopWorkOrder: {
          planPreview: {
            planSource: "heuristic",
            planPreparation: {
              status: "pending",
            },
          },
        },
      },
      updatedAt: new Date("2026-08-20T17:34:55.000Z"),
    },
    assistantContent: "Görev planlanıyor.",
  });

  const planStep = block.steps.find((step) => step.id === "plan");
  assert.equal(planStep?.status, "running");
  assert.equal(
    planStep?.detail,
    "Plan hazırlanıyor; masaüstü yürütmesi beklemede.",
  );
  assert.equal(planStep?.completedAt, undefined);
});

test("buildTaskTraceBlock fails closed for an unknown route", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-unknown-route",
      status: "completed",
      payload: {
        metadata: {
          routeDecision: {
            route: "future_internal_route",
            reason: "Anthropic model id selected by backend policy.",
            userFacingMessage: "Anthropic model id selected by backend policy.",
          },
        },
      },
    },
    assistantContent: "Hazır.",
  });

  assert.equal(block.routeReason, undefined);
  assert.equal(
    block.steps.find((step) => step.id === "route")?.detail,
    "Uygun yol seçildi.",
  );
  assert.doesNotMatch(JSON.stringify(block), /anthropic|model id|backend policy/i);
});

test("agent plan tool transcript is Turkish, timed, and redacted", () => {
  const trace = buildTaskTraceBlock({ task: {
    id: "task-transcript", status: "running", payload: {}, result: {},
    createdAt: new Date("2026-07-19T09:00:00Z"), updatedAt: new Date("2026-07-19T09:00:01Z"),
  }, assistantContent: "Araştırıyorum." });
  const unified = enrichTaskTraceWithAgentPlan({
    trace,
    agentPlan: { steps: [
      { id: "mail", title: "Search", tool_request: { tool: "gmail.search", args: { query: "secret" } } },
      { id: "web", title: "Search", tool_request: { tool: "web.search", args: { query: "secret" } } },
    ] },
    toolFlow: { tools: [
      { name: "gmail.search", ok: true, resultCount: 5, durationMs: 420, errorCode: null },
      { name: "web.search", ok: true, resultCount: 3, durationMs: 610, errorCode: null },
    ] },
    approval: null,
  });
  assert.equal(unified.steps[0]?.label, "Gelen kutunu tarıyorum…");
  assert.equal(unified.steps[0]?.resultSummary, "5 e-posta bulundu.");
  assert.equal(unified.steps[0]?.durationMs, 420);
  assert.equal(unified.steps[1]?.label, "Web'de araştırıyorum…");
  assert.doesNotMatch(unified.steps.map((step) => `${step.label} ${step.detail}`).join(" "), /gmail\.search|web\.search|secret/i);
});

test("agent plan transcript describes professional desktop analysis steps", () => {
  const trace = buildTaskTraceBlock({ task: {
    id: "task-professional-transcript", status: "running", payload: {}, result: {},
    createdAt: new Date("2026-07-23T09:00:00Z"), updatedAt: new Date("2026-07-23T09:00:01Z"),
  }, assistantContent: "Rapor hazırlanıyor." });
  const unified = enrichTaskTraceWithAgentPlan({
    trace,
    agentPlan: { steps: [
      { id: "calc", title: "Calculate", tool_request: { tool: "math_solve", args: { expression: "(12000+8500)*0.2" } } },
      { id: "research", title: "Research", tool_request: { tool: "web_research", args: { query: "KDV kuralları" } } },
      { id: "analyze", title: "Analyze", tool_request: { tool: "text_analyze", args: { sourceContext: "secret" } } },
      { id: "write", title: "Write", tool_request: { tool: "document_write", args: { prompt: "secret" } } },
    ] },
    toolFlow: { tools: [
      { name: "math_solve", ok: true, resultCount: null, durationMs: 50, errorCode: null },
      { name: "web_research", ok: true, resultCount: 2, durationMs: 250, errorCode: null },
      { name: "text_analyze", ok: true, resultCount: null, durationMs: 40, errorCode: null },
    ] },
    approval: null,
  });

  assert.deepEqual(unified.steps.map((step) => step.label), [
    "Hesabı çözüyorum…",
    "Web'de araştırıyorum…",
    "Bağlamı analiz ediyorum…",
    "Belgeyi hazırlıyorum…",
  ]);
  assert.equal(unified.steps[0]?.resultSummary, "Hesap tamamlandı.");
  assert.equal(unified.steps[1]?.resultSummary, "2 kaynak bulundu.");
  assert.equal(unified.steps[2]?.resultSummary, "Analiz tamamlandı.");
  assert.doesNotMatch(unified.steps.map((step) => `${step.label} ${step.detail}`).join(" "), /math_solve|text_analyze|document_write|secret/i);
});

test("agent plan transcript describes connector write tools without leaking args", () => {
  const trace = buildTaskTraceBlock({ task: {
    id: "task-connector-write-transcript", status: "running", payload: {}, result: {},
    createdAt: new Date("2026-07-23T09:00:00Z"), updatedAt: new Date("2026-07-23T09:00:01Z"),
  }, assistantContent: "İşlem hazırlanıyor." });
  const unified = enrichTaskTraceWithAgentPlan({
    trace,
    agentPlan: { steps: [
      { id: "mail", title: "Send", tool_request: { tool: "gmail.send", args: { to: "secret@example.com", body: "secret" } } },
      { id: "calendar", title: "Create", tool_request: { tool: "calendar.create_event", args: { title: "secret" } } },
      { id: "slack", title: "Post", tool_request: { tool: "slack.post_message", args: { channel: "secret" } } },
    ] },
    toolFlow: { tools: [
      { name: "gmail.send", ok: true, resultCount: null, durationMs: 80, errorCode: null },
      { name: "calendar.create_event", ok: true, resultCount: null, durationMs: 90, errorCode: null },
      { name: "slack.post_message", ok: true, resultCount: null, durationMs: 70, errorCode: null },
    ] },
    approval: null,
  });

  assert.deepEqual(unified.steps.map((step) => step.label), [
    "E-posta işlemini hazırlıyorum…",
    "Takvim işlemini hazırlıyorum…",
    "Slack işlemini hazırlıyorum…",
  ]);
  assert.deepEqual(unified.steps.map((step) => step.resultSummary), [
    "E-posta işlemi hazır.",
    "Takvim işlemi hazır.",
    "Slack işlemi hazır.",
  ]);
  assert.doesNotMatch(
    unified.steps.map((step) => `${step.label} ${step.detail}`).join(" "),
    /gmail\.send|calendar\.create_event|slack\.post_message|secret@example\.com|secret/i,
  );
});

test("buildTaskTraceBlock describes the active running phase", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-2",
      status: "running",
      payload: {},
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:01.000Z"),
    },
    assistantContent: "",
  });

  assert.equal(block.status, "running");
  assert.equal(block.progressLabel, "İsteği okuyor");
  assert.equal(block.phase, "intent");
  assert.equal(block.activeStepId, "intent");
  assert.equal(block.summary, "İstek netleşiyor.");
});

test("buildTaskTraceBlock preserves live desktop execution steps", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-live-desktop",
      status: "running",
      payload: {},
      result: {
        executionTrace: {
          title: "Rapor hazırlanıyor",
          activeStepId: "write",
          verification: { status: "pending", privateRuntimeNote: "secret" },
          repairAttempts: 1,
          steps: [
            {
              id: "research",
              label: "Kaynakları araştırıyorum",
              status: "completed",
              capability: "web_research",
              verificationStatus: "passed",
              attemptCount: 1,
            },
            {
              id: "write",
              label: "Raporu yazıyorum",
              status: "running",
              capability: "document_write",
              attemptCount: 2,
              detail: "Özel içerik taşınmayan güvenli durum",
            },
          ],
        },
      },
      createdAt: new Date("2026-07-27T09:00:00.000Z"),
      updatedAt: new Date("2026-07-27T09:00:01.000Z"),
    },
    assistantContent: "",
  });

  assert.equal(block.activeStepId, "write");
  assert.equal(block.progressLabel, "Raporu yazıyorum");
  assert.equal(block.steps.length, 2);
  assert.equal(block.steps[0]?.id, "research");
  assert.equal(block.steps[0]?.capability, "web_research");
  assert.equal(block.steps[0]?.verificationStatus, "passed");
  assert.equal(block.steps[1]?.attemptCount, 2);
  assert.equal(block.verification?.status, "pending");
  assert.equal(block.repairAttempts, 1);
  assert.doesNotMatch(JSON.stringify(block), /privateRuntimeNote|secret/);
});

function toolStepOf(block: ReturnType<typeof buildTaskTraceBlock>) {
  return block.steps.find((step) => step.id === "tool");
}

test("buildTaskTraceBlock surfaces server-side connector tool calls", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-1",
      status: "completed",
      payload: {},
      result: {
        toolFlow: {
          count: 1,
          okCount: 1,
          tools: [{ name: "gmail.search", ok: true, resultCount: 3 }],
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Son üç e-postan burada.",
  });

  const toolStep = toolStepOf(block);
  assert.equal(toolStep?.status, "completed");
  assert.equal(toolStep?.detail, "Gmail · 3 sonuç");
});

test("buildTaskTraceBlock reads tool flow from feed-shaped brain metadata", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-2",
      status: "completed",
      payload: {},
      result: {
        brain: {
          toolFlow: {
            count: 2,
            okCount: 2,
            tools: [
              { name: "gmail.search", ok: true, resultCount: null },
              { name: "calendar.list_events", ok: true, resultCount: null },
            ],
          },
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Hazır.",
  });

  assert.equal(toolStepOf(block)?.detail, "Gmail, Takvim kullanıldı");
});

test("buildTaskTraceBlock reports web grounding in the tool transcript without raw queries", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-web-grounding",
      status: "completed",
      payload: {},
      result: {
        webGroundingUsed: true,
        webSourceCount: 4,
      },
      createdAt: new Date("2026-07-19T09:00:00.000Z"),
      updatedAt: new Date("2026-07-19T09:00:04.000Z"),
      completedAt: new Date("2026-07-19T09:00:04.000Z"),
    },
    assistantContent: "Araştırma hazır.",
  });

  const toolStep = toolStepOf(block);
  assert.equal(toolStep?.status, "completed");
  assert.equal(toolStep?.detail, "Web · 4 kaynak");
  assert.doesNotMatch(JSON.stringify(toolStep), /kedi|query|duckduckgo/i);
});

test("buildTaskTraceBlock reports a tool flow that returned nothing", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-3",
      status: "completed",
      payload: {},
      result: {
        toolFlow: {
          count: 1,
          okCount: 0,
          tools: [{ name: "drive.search", ok: false, resultCount: null }],
        },
      },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Bir şey bulamadım.",
  });

  assert.equal(toolStepOf(block)?.detail, "Drive denendi");
});

test("buildTaskTraceBlock still reports no tool when none ran", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-tool-4",
      status: "completed",
      payload: {},
      result: { text: "Merhaba!" },
      createdAt: new Date("2026-06-23T09:00:00.000Z"),
      updatedAt: new Date("2026-06-23T09:00:04.000Z"),
      completedAt: new Date("2026-06-23T09:00:04.000Z"),
    },
    assistantContent: "Merhaba!",
  });

  const toolStep = toolStepOf(block);
  assert.equal(toolStep?.status, "skipped");
  assert.equal(toolStep?.detail, "Araç gerekmedi.");
});

// ---------------------------------------------------------------------------
// Mobil onay düğmeleri blok durumundan DEĞİL adım durumundan türetilir
// (`needsApproval = steps.contains { $0.state == .waitingApproval }`). Canlı
// arıza (2026-08-21, görev 45dd0087): görev `waiting_approval`,
// `approval_request` eksiksiz, ama hiçbir adım öyle işaretlenmediği için
// telefonda Onayla/Reddet HİÇ çıkmadı — backend'e tek bir approval isteği
// gelmedi ve görev 9 dakika sonra iptal oldu.
// ---------------------------------------------------------------------------
test("buildTaskTraceBlock marks a step as waiting_approval so mobile can render the approval controls", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-approval-1",
      status: "waiting_approval",
      payload: {
        desktopWorkOrder: {
          planPreview: { planSource: "server_materialized" },
        },
        metadata: {
          understanding: { intent: { primaryIntent: "automation" } },
        },
      },
      createdAt: new Date("2026-08-21T16:46:25.000Z"),
      updatedAt: new Date("2026-08-21T16:47:19.000Z"),
      runtimeConnectionId: "runtime-1",
    },
    assistantContent: "Görev için açık onay gerekiyor.",
  });

  const waiting = block.steps.filter((step) => step.status === "waiting_approval");
  assert.equal(waiting.length, 1);
  assert.equal(block.activeStepId, waiting[0]?.id);
});

test("buildTaskTraceBlock leaves a completed task without any waiting_approval step", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-approval-2",
      status: "completed",
      payload: {
        metadata: {
          understanding: { intent: { primaryIntent: "automation" } },
        },
      },
      createdAt: new Date("2026-08-21T16:46:25.000Z"),
      updatedAt: new Date("2026-08-21T16:47:19.000Z"),
      completedAt: new Date("2026-08-21T16:47:19.000Z"),
    },
    assistantContent: "Bitti.",
  });

  assert.equal(
    block.steps.some((step) => step.status === "waiting_approval"),
    false,
  );
});

test("buildTaskTraceBlock exposes clarification without manufacturing computer permission", () => {
  const updatedAt = new Date("2026-08-24T18:00:00.000Z");
  const block = buildTaskTraceBlock({
    task: {
      id: "task-clarification",
      status: "waiting_approval",
      updatedAt,
      approvalRequest: {
        kind: "clarification",
        interaction: { kind: "clarification" },
        question: "Hangi klasörü kullanmalıyım?",
        availableActions: ["answer"],
      },
      payload: {
        metadata: {
          routeDecision: {
            route: "desktop_runtime",
            intent: "desktop_cowork",
          },
        },
      },
    },
  });

  assert.deepEqual(block.interaction, {
    kind: "clarification",
    question: "Hangi klasörü kullanmalıyım?",
  });
  assert.equal(block.needsApproval, false);
  assert.deepEqual(block.availableActions, ["answer"]);
  assert.equal(block.updatedAt, updatedAt.toISOString());
});
