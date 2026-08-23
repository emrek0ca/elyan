import assert from "node:assert/strict";
import test from "node:test";
import { compileOutputContract } from "./output-contract.js";
import { resolveConversationReference } from "./reference-resolver.js";
import { selectToolSkillForTurn } from "./tool-skill-selector.js";
import { buildDesktopWorkOrder } from "../../modules/tasks/desktop-work-order.js";
import type { CommandRouteDecision } from "../../modules/routing-policy/service.js";

test("output contract treats four-page PDF writing as document artifact creation", () => {
  const contract = compileOutputContract({
    message:
      "Merhaba dif geo kullanım alanlarıyla alakalı 4 sayfalık PDF yazar mısın",
  });
  assert.equal(contract.operation, "create");
  assert.equal(contract.outputKind, "document");
  assert.equal(contract.outputFormat, "pdf");
  assert.equal(contract.pageCount, 4);
  assert.equal(contract.requiresArtifact, true);
});

test("output contract resolves referential PDF and Excel conversions as transforms", () => {
  const pdf = compileOutputContract({ message: "Bunu PDF yap" });
  assert.equal(pdf.operation, "transform");
  assert.equal(pdf.sourceReference, "previous_answer");
  assert.equal(pdf.outputKind, "document");
  assert.equal(pdf.outputFormat, "pdf");

  const xlsx = compileOutputContract({ message: "Şunu Excele dönüştür" });
  assert.equal(xlsx.operation, "transform");
  assert.equal(xlsx.sourceReference, "previous_answer");
  assert.equal(xlsx.outputKind, "table");
  assert.equal(xlsx.outputFormat, "xlsx");
});

test("output contract does not confuse fotosentez with a photo request", () => {
  const contract = compileOutputContract({
    message: "Fotosentez nasıl çalışır",
  });

  assert.equal(contract.operation, "answer");
  assert.equal(contract.outputKind, "chat_reply");
  assert.equal(contract.outputFormat, null);
  assert.equal(contract.requiresArtifact, false);
});

test("output contract keeps local read-only lookups out of artifact generation", () => {
  const message =
    "Bilgisayarda açık olan uygulamaları gözlemle ve masaüstünde en son değiştirilen rapor dosyasını bulup yalnızca dosya adını söyle. Hiçbir şeyi değiştirme, silme veya kaydetme.";
  const desktopObservation = compileOutputContract({
    title: "Bilgisayar durumunu salt-okuma analiz et",
    message,
  });
  const documentRead = compileOutputContract({
    message: "Masaüstümdeki PDF dosyasını oku ve özetle",
  });

  for (const contract of [desktopObservation, documentRead]) {
    assert.equal(contract.operation, "answer");
    assert.equal(contract.outputKind, "chat_reply");
    assert.equal(contract.outputFormat, null);
    assert.equal(contract.requiresArtifact, false);
  }

  const routeDecision = {
    route: "desktop_runtime",
    mode: "executable_task",
    capabilities: ["file_find"],
    privacyClass: "local_private",
    requiresApproval: false,
    reason: "read-only desktop observation",
    intent: "local_file_request",
    confidence: 0.9,
    requiredRuntime: "desktop",
    privacyLevel: "high",
    shouldAskClarification: false,
    failClosedReason: "desktop_runtime_selected_target",
    selectedWorkload: "desktop_handoff",
    taskRoute: {
      target: "desktop_runtime",
      operationalRoute: "desktop_runtime",
      executionPlan: ["desktop_runtime"],
      reason: "read-only desktop observation",
      needsDesktop: true,
      needsPrivateDesktopData: true,
      needsUserApproval: false,
      requiredCapabilities: ["file_find"],
    },
  } satisfies CommandRouteDecision;
  const workOrder = buildDesktopWorkOrder({
    message,
    title: "Bilgisayar durumu",
    routeDecision,
    requestedCapabilities: [],
  });
  assert.deepEqual(
    workOrder.planPreview.steps.map((step) => step.capability),
    ["desktop_os.processes", "file_find"],
  );
  assert.equal(workOrder.planPreview.planSource, "deterministic_registry");
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), false);
  assert.equal(
    workOrder.expectedOutputs.some(
      (output) => output.kind === "artifact" && output.required,
    ),
    false,
  );
});

test("reference resolver carries previous assistant answer for 'bunu pdf yap'", () => {
  const resolved = resolveConversationReference({
    message: "bunu pdf yap",
    conversation: [
      { role: "user", content: "Dif geo kullanım alanlarını anlat" },
      { role: "assistant", content: "Diferansiyel geometri fizik, robotik ve grafik alanlarında kullanılır." },
    ],
  });
  assert.equal(resolved.sourceReference, "previous_answer");
  assert.match(resolved.sourceText ?? "", /Diferansiyel geometri/);
});

test("tool skill selector prefers the artifact surface over plain chat", () => {
  const selected = selectToolSkillForTurn({
    message: "Bu metni Excel dosyasına dönüştür",
  });
  assert.equal(selected.selected.id, "spreadsheet.write");
  assert.equal(selected.selected.workload, "table_generate");
  assert.equal(selected.selected.score > 0.8, true);
});
