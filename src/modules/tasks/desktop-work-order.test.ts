import test from "node:test";
import assert from "node:assert/strict";
import { buildDesktopWorkOrder } from "./desktop-work-order.js";
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
