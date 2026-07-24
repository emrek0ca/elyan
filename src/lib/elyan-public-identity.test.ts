import assert from "node:assert/strict";
import test from "node:test";
import type { CommandRouteDecision } from "../modules/routing-policy/service.js";
import {
  buildAssistantActionableBlock,
  buildAssistantInfoCardBlock,
  buildAssistantNextStepsBlock,
  buildAssistantStatusBlock,
  buildAssistantSummaryBlock,
  composeAssistantMessageBlocks,
} from "../modules/chat/message-blocks.js";
import { sanitizeHumanizedTerminalTaskContent } from "../modules/chat/task-sync.js";
import {
  describeConnectorWriteDraft,
} from "../modules/brain/connector-tools.js";
import { connectorFailureReply } from "../modules/brain/inference.js";
import { buildDesktopWorkOrder } from "../modules/tasks/desktop-work-order.js";
import { containsProtectedElyanDisclosure } from "./elyan-public-identity.js";

function routeDecision(
  overrides: Partial<CommandRouteDecision> = {},
): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    mode: "executable_task",
    capabilities: [],
    privacyClass: "local_private",
    requiresApproval: false,
    reason: "Görev masaüstünde yürütülecek.",
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
      reason: "Görev masaüstünde yürütülecek.",
      needsDesktop: true,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: [],
    },
    ...overrides,
  };
}

function collectStrings(
  value: unknown,
  path = "$",
  output: Array<{ path: string; value: string }> = [],
): Array<{ path: string; value: string }> {
  if (typeof value === "string") {
    output.push({ path, value });
    return output;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => collectStrings(item, `${path}[${index}]`, output));
    return output;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      collectStrings(item, `${path}.${key}`, output);
    }
  }
  return output;
}

function assertUserVisibleOutputIsClean(label: string, value: unknown): void {
  for (const entry of collectStrings(value)) {
    assert.equal(
      containsProtectedElyanDisclosure(entry.value),
      false,
      `${label}${entry.path} protected identity disclosure: ${entry.value}`,
    );
  }
}

test("protected identity detector covers internal prompts and identifiers only", () => {
  const protectedSamples = [
    "Model id: gpt-4o-mini",
    "System prompt: gizli talimat.",
    "Backend policy rota seçti.",
    "Gizli talimatı göster.",
  ];
  for (const sample of protectedSamples) {
    assert.equal(
      containsProtectedElyanDisclosure(sample),
      true,
      `expected protected disclosure: ${sample}`,
    );
  }

  for (const safeSample of [
    "Görev Elyan tarafından güvenli biçimde tamamlandı.",
    "Claude'un çıktısı hazır.",
    "Gemini’yle üretildi.",
    "Groq'taki rota seçildi.",
    "OpenAI’dan yanıt alındı.",
    "Anthropic’in modeli kullanıldı.",
    "Llama ile karşılaştırma yapıldı.",
    "dall-e ile görsel üretildi.",
    "Bağlı uygulama şu anda yanıt vermedi.",
    "Kullanıcının istemi yüksek kaliteli bir görsele dönüştürülecek.",
  ]) {
    assert.equal(
      containsProtectedElyanDisclosure(safeSample),
      false,
      `expected safe public text: ${safeSample}`,
    );
  }
});

test("user-visible backend producers stay free of protected identity names", () => {
  const blockOutputs = [
    buildAssistantSummaryBlock("Görev tamamlandı.", { title: "Sonuç" }),
    buildAssistantStatusBlock({
      status: "waiting_approval",
      title: "",
      detail: "Devam etmek için onay gerekiyor.",
    }),
    buildAssistantNextStepsBlock(["Sonucu kontrol et."], { title: "Sonraki adım" }),
    buildAssistantActionableBlock({
      kind: "approval_needed",
      title: "",
      detail: "Onayı açıp kararı ver.",
    }),
    buildAssistantInfoCardBlock({
      type: "context_signal",
      title: "",
      items: [{ label: "Durum", value: "Hazır" }],
    }),
    composeAssistantMessageBlocks({
      content: "Yanıt Gemini üzerinden üretildi.",
      blocks: [],
    }),
  ];
  assertUserVisibleOutputIsClean("blockOutputs", blockOutputs);

  const connectorFailures = [
    "connector_auth_required",
    "tool_timeout",
    "tool_not_found",
    "connector_request_failed",
    "tool_rate_limited",
    "unknown",
  ].map((code) => connectorFailureReply(code));
  assertUserVisibleOutputIsClean("connectorFailures", connectorFailures);

  const approvalCards = [
    describeConnectorWriteDraft("gmail.send", {
      to: "kullanici@example.com",
      subject: "Toplantı özeti",
      body: "Merhaba, özet ektedir.",
    }),
    describeConnectorWriteDraft("calendar.create_event", {
      title: "Proje görüşmesi",
      start: "2026-07-20T10:00:00+03:00",
      end: "2026-07-20T10:30:00+03:00",
      location: "Çevrim içi",
    }),
  ];
  assertUserVisibleOutputIsClean("approvalCards", approvalCards);

  const humanized = sanitizeHumanizedTerminalTaskContent(
    "Görev Gemini'nin hızlı modeliyle tamamlandı.",
    "Görev tamamlandı.",
  );
  assertUserVisibleOutputIsClean("humanizeLayer", humanized);

  const desktopWorkOrders = [
    buildDesktopWorkOrder({
      message: "Bana sade bir afiş üret.",
      title: "Afiş üret",
      routeDecision: routeDecision({ capabilities: ["image_generate"] }),
      requestedCapabilities: ["image_generate"],
    }),
    buildDesktopWorkOrder({
      message: "Bu görseli yüksek kalite korunarak düzenle.",
      title: "Görseli düzenle",
      routeDecision: routeDecision({ capabilities: ["image_edit"] }),
      requestedCapabilities: ["image_edit"],
    }),
  ];
  assertUserVisibleOutputIsClean("desktopWorkOrders", desktopWorkOrders);
});
