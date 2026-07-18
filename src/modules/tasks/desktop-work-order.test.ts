import test from "node:test";
import assert from "node:assert/strict";
import {
  buildDesktopWorkOrder,
  isDeterministicDesktopAppWorkOrder,
  isDeterministicDesktopFastWorkOrder,
  parseDirectDesktopAppCommand,
  parseDirectImageFetchCommand,
} from "./desktop-work-order.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import type { UnderstandingEnvelope } from "../../core/understanding/types.js";

function routeDecision(overrides: Partial<CommandRouteDecision> = {}): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    mode: "executable_task",
    capabilities: [],
    privacyClass: "local_private",
    requiresApproval: false,
    reason: "Dispatch",
    intent: "desktop_cowork",
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
      reason: "Dispatch",
      needsDesktop: true,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: [],
    },
    ...overrides,
  };
}

test("buildDesktopWorkOrder turns a mobile dispatch prompt into typed execution data", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Chrome'da https://elyan.ai sayfasını aç ve kontrol et.",
    title: "Sayfayı kontrol et",
    routeDecision: routeDecision({ capabilities: ["browser_control"] }),
    requestedCapabilities: [],
  });

  assert.equal(workOrder.schema, "elyan.desktop_work_order.v1");
  assert.equal(workOrder.goal.kind, "browser_task");
  assert.notEqual(workOrder.goal.summary, "Chrome'da https://elyan.ai sayfasını aç ve kontrol et.");
  assert.match(workOrder.goal.sourceTextHash, /^[a-f0-9]{24}$/);
  assert.equal(workOrder.entities.some((entity) => entity.type === "url" && entity.value.includes("elyan.ai")), true);
  assert.equal(workOrder.requiredCapabilities.includes("browser_control"), true);
  assert.equal(workOrder.planPreview.steps.some((step) => step.capability === "browser_control"), true);
  assert.equal(workOrder.expectedOutputs.some((output) => output.kind === "chat_result"), true);
});

test("buildDesktopWorkOrder keeps private file requests local and evidence-gated", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Masaüstündeki son PDF'i özetle.",
    title: "PDF özeti",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
  });

  assert.equal(workOrder.localContextNeeded.includes("filesystem"), true);
  assert.equal(workOrder.requiredCapabilities.includes("document_read"), true);
  assert.equal(workOrder.requiredCapabilities.includes("filesystem_read"), false);
  assert.equal(workOrder.planPreview.privacyClass, "local_private");
  assert.equal(workOrder.verificationRules.some((rule) => rule.evidence === "tool_result"), true);
});

test("remote MCP work orders keep least-privilege scope and private routing", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "GitHub repolarımı göster",
    title: "GitHub repoları",
    routeDecision: routeDecision({ capabilities: ["mcp_call_tool"] }),
    requestedCapabilities: ["mcp_call_tool"],
  });

  assert.deepEqual(workOrder.requiredCapabilities, ["mcp_call_tool"]);
  assert.deepEqual(workOrder.planPreview.steps, []);
  assert.equal(
    workOrder.requiredCapabilities.includes("desktop_operator.run"),
    false,
  );
  assert.equal(workOrder.planPreview.privacyClass, "local_private");
});

test("buildDesktopWorkOrder emits a direct app capability with the parsed application name", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Hesap Makinesi uygulamasını aç ve açıldığını doğrula.",
    title: "Hesap Makinesi'ni aç",
    routeDecision: routeDecision({ capabilities: ["open_app"] }),
    requestedCapabilities: ["open_app"],
  });

  const step = workOrder.planPreview.steps.find((item) => item.capability === "open_app");
  assert.ok(step);
  assert.equal(step.args.app_name, "Hesap Makinesi");
  assert.equal(workOrder.planPreview.steps.some((item) => item.capability === "desktop_operator.run"), false);
});

test("direct desktop app commands support terse Turkish and skip generic planning", () => {
  assert.deepEqual(parseDirectDesktopAppCommand("TextEdit aç"), {
    capability: "open_app",
    appName: "TextEdit",
  });
  assert.deepEqual(parseDirectDesktopAppCommand("Chrome'u kapat"), {
    capability: "close_app",
    appName: "Chrome",
  });
  assert.equal(
    isDeterministicDesktopAppWorkOrder(
      routeDecision({ capabilities: ["open_app"] }),
      "Lütfen Hesap Makinesi uygulamasını aç.",
    ),
    true,
  );

  const workOrder = buildDesktopWorkOrder({
    message: "Chrome'u kapat",
    title: "Chrome'u kapat",
    routeDecision: routeDecision({ capabilities: [] }),
    requestedCapabilities: [],
  });
  const closeStep = workOrder.planPreview.steps.find((step) => step.capability === "close_app");
  assert.ok(closeStep);
  assert.equal(closeStep.args.app_name, "Chrome");
  assert.equal(workOrder.planPreview.steps.some((step) => step.capability === "desktop_operator.run"), false);
});

test("direct image download becomes an artifact-producing image_fetch plan", () => {
  assert.deepEqual(
    parseDirectImageFetchCommand("Kedi resmi indir. İndirilen dosyayı doğrula."),
    { query: "Kedi", destination: "~/Desktop", count: 1 },
  );
  assert.deepEqual(
    parseDirectImageFetchCommand("İnternetten 3 adet aslan görseli indirilenlere indir"),
    { query: "aslan", destination: "~/Downloads", count: 3 },
  );
  assert.equal(
    isDeterministicDesktopFastWorkOrder(routeDecision(), "Kedi resmi indir"),
    true,
  );

  const workOrder = buildDesktopWorkOrder({
    message: "Kedi resmi indir. İndirilen dosyayı doğrula.",
    title: "Kedi resmi indir",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
  });
  const step = workOrder.planPreview.steps.find((item) => item.capability === "image_fetch");
  assert.ok(step);
  assert.equal(step.args.query, "Kedi");
  assert.equal(step.args.destination, "~/Desktop");
  assert.equal(workOrder.requiredCapabilities.includes("desktop_operator.run"), false);
  assert.equal(workOrder.expectedOutputs.some((output) => output.kind === "artifact" && output.required), true);
});

test("research presentation becomes a typed evidence-gated desktop chain", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Kuantum bilgisayarlarını web'den araştırıp 5 slaytlık sunum olarak masaüstüne hazırla.",
    title: "Kuantum bilgisayarları sunumu",
    routeDecision: routeDecision({ capabilities: ["desktop.runtime"] }),
    requestedCapabilities: [],
  });

  assert.equal(workOrder.goal.kind, "presentation_task");
  assert.deepEqual(
    workOrder.planPreview.steps.map((step) => step.capability),
    ["web_research", "presentation_write"],
  );
  assert.equal(workOrder.requiredCapabilities.includes("browser_control"), false);
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), false);
  assert.equal(workOrder.requiredCapabilities.includes("desktop_operator.run"), false);

  const presentation = workOrder.planPreview.steps[1];
  assert.equal(presentation?.args.sourceContext, undefined);
  assert.match(String(presentation?.args.prompt ?? ""), /5 slaytlık sunum/iu);
  assert.match(String(presentation?.args.outputPath ?? ""), /^~\/Desktop\/.+\.pptx$/u);
  assert.equal(workOrder.expectedOutputs.filter((output) => output.kind === "artifact").length, 1);
  assert.equal(workOrder.expectedOutputs.filter((output) => output.kind === "file_update").length, 1);
});

test("presentation creation does not add a second generic document writer", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "İklim değişikliğini araştır ve sonuçlardan bir sunum oluştur.",
    title: "İklim sunumu",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
  });

  assert.deepEqual(
    workOrder.planPreview.steps.map((step) => step.capability),
    ["web_research", "presentation_write"],
  );
});

test("buildDesktopWorkOrder carries typed understanding without forwarding a raw execution prompt", () => {
  const envelope: UnderstandingEnvelope = {
    schema_version: "2026-07-understanding-envelope-v2",
    intent: {
      name: "document",
      action: "create",
      topic: "Aylık gelir raporu",
      confidence: 0.96,
      source: "typed_extractor",
    },
    entities: [{ type: "amount", value: "12000", normalized: "12000", confidence: 0.98, source: "typed_extractor" }],
    constraints: [{ kind: "footer_text", value: "Emre", confidence: 0.99, source: "typed_extractor", explicit: true }],
    desired_outputs: [{ kind: "pdf", format: "pdf", target: "artifact", confidence: 0.99, constraints: ["footer_text"] }],
    success_criteria: [{ kind: "footer_preserved", description: "Footer en altta olmalı.", evidenceRequired: "artifact", confidence: 0.95 }],
    ambiguities: [],
    risk: { privacy: "low", safety: "low", cost: "low", latency: "low", local_private: false, side_effect: false, prompt_injection: false, reasons: [] },
    required_capabilities: [{ name: "document.write", executionSurface: "desktop", permission: "write", confidence: 0.96 }],
    memory_candidates: [],
    confidence: 0.96,
    source: "typed_extractor",
  };

  const workOrder = buildDesktopWorkOrder({
    message: "Aylık gelir raporunu PDF yap ve en alta Emre yaz.",
    title: "Gelir raporu",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
    understandingEnvelope: envelope,
  });

  assert.equal(workOrder.understanding?.schemaVersion, envelope.schema_version);
  assert.equal(workOrder.understanding?.constraints[0]?.kind, "footer_text");
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), true);
  assert.equal(workOrder.requiredCapabilities.includes("canvas_write"), true);
  assert.equal(workOrder.planPreview.steps.some((step) => step.capability === "canvas_write"), true);
  assert.equal("message" in workOrder, false);
  assert.equal("prompt" in workOrder, false);
});

test("close-app browser task does not append a generic browser search step", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Chrome u kapat",
    title: "Masaüstü görevi — Chrome u kapat — Bağlam: browser",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
  });

  const capabilities = workOrder.planPreview.steps.map((step) => step.capability);
  assert.equal(capabilities.includes("close_app"), true);
  assert.equal(capabilities.includes("browser_control"), false);
});

// ── Türkçe kelime sınırı dönüşümü ölçümü ─────────────────────────────
// Dönüşümden önce bu ifadeler HİÇBİR kalıba takılmıyordu: "afiş" (ş ile
// biter), "üret"/"çevir" (ü/ç ile başlar), "şunu" — ham ASCII \b bu
// kenarlarda asla eşleşmez, istek jenerik desktop_cowork'e düşüyordu.

test("saf Türkçe 'afiş üret' image_generate rotasına gider", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Bana bir afiş üret lütfen",
    title: "Afiş",
    routeDecision: routeDecision({ capabilities: [] }),
    requestedCapabilities: [],
  });
  assert.equal(workOrder.goal.kind, "image_generate");
});

test("saf Türkçe 'şunu anime tarzında çevir' image_edit sayılır", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Şunu anime tarzında çevir",
    title: "Görsel",
    routeDecision: routeDecision({ capabilities: [] }),
    requestedCapabilities: [],
  });
  assert.equal(workOrder.goal.kind, "image_edit");
});

test("saf Türkçe 'masaüstüne kaydet' dosya yeteneğini işaretler", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Raporu masaüstüne kaydet",
    title: "Rapor",
    routeDecision: routeDecision({ capabilities: [] }),
    requestedCapabilities: [],
  });
  // "masaüstüne" → document_read, "kaydet" → document_write; dönüşümden
  // önce her iki alternatif de (ü-başlangıç/ş-kenar) hiç eşleşmiyordu.
  assert.equal(workOrder.requiredCapabilities.includes("document_read"), true);
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), true);
});
