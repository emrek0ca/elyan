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

test("buildTaskTraceBlock exposes a safe route rationale", () => {
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

  assert.equal(
    block.routeReason,
    "Elyan bunu sohbet olarak işledi çünkü istek özel yerel veri veya bilgisayar erişimi gerektirmiyor.",
  );
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
