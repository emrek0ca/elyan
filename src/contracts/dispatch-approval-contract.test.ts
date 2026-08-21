import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { buildTaskTraceBlock } from "../modules/chat/task-trace.js";

// ---------------------------------------------------------------------------
// ONAY SÖZLEŞMESİ TEK YERDE YAZILIR — istemci onu TÜRETMEZ.
//
// Canlı arıza (2026-08-21, görev 45dd0087): görev `waiting_approval`,
// `approval_request` eksiksiz, backend `/approval` ucu hazır. Ama mobil onay
// ihtiyacını adım durumlarından türetiyordu ve sunucu hiçbir adımı
// `waiting_approval` işaretlemiyordu. Kullanıcıya düğme HİÇ çıkmadı; bastığını
// sandı, backend'e tek bir approval isteği gelmedi, görev 9 dakika sonra iptal
// oldu.
// ---------------------------------------------------------------------------

const require = createRequire(import.meta.url);
const schema = require("../../contracts/generated/assistant-blocks.schema.json") as {
  $defs: Record<string, { properties: { data: { properties: Record<string, unknown> } } }>;
};

function waitingApprovalBlock() {
  return buildTaskTraceBlock({
    task: {
      id: "task-contract-1",
      status: "waiting_approval",
      payload: {
        desktopWorkOrder: { planPreview: { planSource: "server_materialized" } },
        metadata: { understanding: { intent: { primaryIntent: "automation" } } },
      },
      createdAt: new Date("2026-08-21T16:46:25.000Z"),
      updatedAt: new Date("2026-08-21T16:47:19.000Z"),
      runtimeConnectionId: "runtime-1",
    },
    assistantContent: "Görev için açık onay gerekiyor.",
  });
}

test("the published block schema declares needsApproval for both dispatch aliases", () => {
  for (const name of ["DispatchWidgetBlock", "TaskTraceBlock"]) {
    const props = schema.$defs[name]?.properties.data.properties;
    assert.ok(props, `${name} şemada yok`);
    assert.ok(
      Object.hasOwn(props, "needsApproval"),
      `${name} onay alanını YAYIMLAMIYOR — istemci türetmeye mahkûm kalır`,
    );
  }
});

test("a waiting-approval block carries every field the client needs to act", () => {
  const block = waitingApprovalBlock();

  // 1) Açık alan.
  assert.equal(block.needsApproval, true);
  // 2) Türetmeye dayanan istemciler için adım durumu da doğru.
  const waiting = block.steps.filter((step) => step.status === "waiting_approval");
  assert.equal(waiting.length, 1);
  assert.equal(block.activeStepId, waiting[0]?.id);
  // 3) Onay isteğini gönderebilmek için görev kimliği.
  assert.ok(block.taskId && block.taskId.length > 0);
  assert.equal(block.status, "waiting_approval");
});

test("a settled block claims neither the flag nor a waiting step", () => {
  const block = buildTaskTraceBlock({
    task: {
      id: "task-contract-2",
      status: "completed",
      payload: { metadata: { understanding: { intent: { primaryIntent: "automation" } } } },
      createdAt: new Date("2026-08-21T16:46:25.000Z"),
      updatedAt: new Date("2026-08-21T16:47:19.000Z"),
      completedAt: new Date("2026-08-21T16:47:19.000Z"),
    },
    assistantContent: "Bitti.",
  });

  assert.notEqual(block.needsApproval, true);
  assert.equal(block.steps.some((step) => step.status === "waiting_approval"), false);
});
