import assert from "node:assert/strict";
import test from "node:test";
import type { IntentClassification } from "../../core/understanding/types.js";
import { buildTypedUnderstandingEnvelope } from "../../core/understanding/understanding-envelope.js";
import { buildDesktopWorkOrder } from "./desktop-work-order.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";

function intent(primaryIntent: IntentClassification["primaryIntent"]): IntentClassification {
  return {
    primaryIntent,
    secondaryIntents: [],
    requiresLocalRuntime: false,
    requiresRetrieval: false,
    requiresToolUse: primaryIntent !== "chat",
    requiresCitation: primaryIntent === "research",
    requiresLongRunningTask: primaryIntent !== "chat",
    privacyRisk: "low",
    confidence: 0.84,
    reason: "quality_matrix",
    taskFrame: {
      goal: "quality matrix",
      likelyAnswerShape: "structured",
      reasoningMode: "balanced",
      shouldClarify: false,
    },
    ecosystemHints: [],
    routingHints: {
      mode: primaryIntent === "chat" ? "fast" : "task",
      preferredCapabilities: [],
      avoidCloud: false,
      requiresLocalRuntime: false,
    },
  };
}

function route(capabilities: string[] = []): CommandRouteDecision {
  return {
    route: "desktop_runtime",
    mode: "executable_task",
    capabilities,
    privacyClass: capabilities.some((capability) => capability.startsWith("desktop_operator")) ? "local_private" : "public_text",
    requiresApproval: capabilities.some((capability) => capability.startsWith("desktop_operator") || capability === "browser_control"),
    reason: "quality_matrix",
    intent: "desktop_cowork",
    confidence: 0.88,
    requiredRuntime: "desktop",
    privacyLevel: "medium",
    shouldAskClarification: false,
    failClosedReason: "desktop_runtime_selected_target",
    selectedWorkload: "desktop_handoff",
    taskRoute: {
      target: "desktop_runtime",
      operationalRoute: "desktop_runtime",
      executionPlan: ["desktop_runtime"],
      reason: "quality_matrix",
      needsDesktop: true,
      needsPrivateDesktopData: false,
      needsUserApproval: false,
      requiredCapabilities: capabilities,
    },
  };
}

const scenarios: Array<{
  message: string;
  primaryIntent: IntentClassification["primaryIntent"];
  metadata?: Record<string, unknown>;
  expectedReference?: string;
  expectedFormat?: string;
  desktopCapabilities?: string[];
}> = [
  { message: "Selam", primaryIntent: "chat" },
  { message: "Bana kısa bir matematik teoremi söyle", primaryIntent: "math" },
  { message: "Diferansiyel geometri kullanım alanlarıyla alakalı 4 sayfalık PDF yaz", primaryIntent: "document", expectedFormat: "pdf" },
  { message: "Bu raporu Word olarak ver", primaryIntent: "document", expectedFormat: "docx", expectedReference: "previous_answer" },
  { message: "Bunu PDF yap", primaryIntent: "document", expectedFormat: "pdf", expectedReference: "previous_answer" },
  { message: "Excele dönüştür", primaryIntent: "document", expectedFormat: "xlsx" },
  { message: "Kapı tamiri ve menteşe tutarlarını Excel tablo yap", primaryIntent: "document", expectedFormat: "xlsx" },
  { message: "1,2,3 sayılarının karelerini tablo halinde göster", primaryIntent: "document" },
  { message: "Satış verilerinden grafik oluştur", primaryIntent: "document" },
  { message: "Bir kedi görseli çiz", primaryIntent: "image", expectedFormat: "png" },
  { message: "Hayır bu görsel beyaz olsun", primaryIntent: "image", expectedFormat: "png", expectedReference: "latest_artifact", metadata: { hasLatestArtifact: true, latestArtifact: { id: "img1", kind: "image", prompt: "tekir kedi" } } },
  { message: "Daha sinematik yap", primaryIntent: "image", expectedReference: "latest_artifact", metadata: { hasLatestArtifact: true, latestArtifact: { id: "img2", kind: "image", prompt: "beyaz kedi" } } },
  { message: "Avukat gibi bu davayı analiz et ve savunma dilekçesi hazırla", primaryIntent: "document", expectedFormat: "docx", desktopCapabilities: ["document_read", "web_research", "text_analyze", "document_write"] },
  { message: "Tahlilleri yorumla ve rapor çıkar: Hb 10.5 ferritin 8", primaryIntent: "document", expectedFormat: "docx", desktopCapabilities: ["document_read", "text_analyze", "document_write"] },
  { message: "Mühendislik raporu hazırla ve kaynakları araştır", primaryIntent: "research", expectedFormat: "docx", desktopCapabilities: ["web_research", "text_analyze", "document_write"] },
  { message: "Öğrenci için kuantum annealing sunumu hazırla", primaryIntent: "document", desktopCapabilities: ["web_research", "text_analyze", "presentation_write"] },
  { message: "Chrome'u aç ve yeni sekmede kuantum optimizasyon ara", primaryIntent: "browser", desktopCapabilities: ["open_app", "browser_control", "desktop_operator.observe_screen"] },
  { message: "Ekranda ne var?", primaryIntent: "computer", desktopCapabilities: ["analyze_screen"] },
  { message: "Ekrandaki butona tıkla ve sonucu doğrula", primaryIntent: "computer", desktopCapabilities: ["desktop_operator.observe_screen", "desktop_operator.execute_action"] },
  { message: "Safari'yi aç", primaryIntent: "automation", desktopCapabilities: ["open_app"] },
  { message: "Açık uygulamaları listele", primaryIntent: "computer", desktopCapabilities: ["desktop_os.processes"] },
  { message: "Masaüstündeki son PDF'i özetle", primaryIntent: "document", desktopCapabilities: ["document_read", "text_analyze"] },
  { message: "Bu klasördeki dosya ağacını çıkar", primaryIntent: "computer", desktopCapabilities: ["directory_tree"] },
  { message: "Bu metni resmi dile çevir", primaryIntent: "writing" },
  { message: "Bu cevabı daha kısa yaz", primaryIntent: "writing", expectedReference: "previous_answer" },
  { message: "Devam et", primaryIntent: "chat", expectedReference: "previous_answer" },
  { message: "Hani?", primaryIntent: "chat", expectedReference: "previous_answer" },
  { message: "Yanlış anladın, bunu rapora çevir", primaryIntent: "document", expectedReference: "previous_answer" },
  { message: "PDF olarak ver ama tablo kullanma", primaryIntent: "document", expectedFormat: "pdf" },
  { message: "Word sonra PDF olarak oluştur", primaryIntent: "document", expectedFormat: "docx" },
  { message: "CSV verisini XLSX dosyasına çevir", primaryIntent: "document", expectedFormat: "xlsx" },
  { message: "Grafiği açıklayıp raporlaştır", primaryIntent: "document", expectedFormat: "docx" },
  { message: "Bu görseldeki yazıyı oku", primaryIntent: "image" },
  { message: "Fotoğraftaki tabloyu Excel yap", primaryIntent: "image", expectedFormat: "xlsx" },
  { message: "Makine öğrenmesi manifold öğrenme raporu hazırla", primaryIntent: "document", expectedFormat: "docx" },
  { message: "A değer 10 maliyet 4, B değer 7 maliyet 3 kapasite 10; optimize et", primaryIntent: "math", desktopCapabilities: ["quantum_model_problem", "quantum_run_experiment", "quantum_compare_classical", "quantum_generate_report"] },
  { message: "Karar değişkenleri, amaç fonksiyonu ve kısıtlarla modelle", primaryIntent: "math", desktopCapabilities: ["quantum_model_problem"] },
  { message: "QAOA ile çöz ve klasik sonuçla karşılaştır", primaryIntent: "math", desktopCapabilities: ["quantum_run_experiment", "quantum_compare_classical"] },
  { message: "Son çözümü rapor olarak kaydet", primaryIntent: "document", expectedReference: "previous_answer", expectedFormat: "docx" },
  { message: "Kaynaklı kısa araştırma yap", primaryIntent: "research" },
  { message: "Güncel batarya trendlerini araştır ve rapor yaz", primaryIntent: "research", expectedFormat: "docx" },
  { message: "Bu maili taslak haline getir", primaryIntent: "writing" },
  { message: "Maili gönder", primaryIntent: "automation", desktopCapabilities: ["email_send"] },
  { message: "Takvimime toplantı ekle", primaryIntent: "automation", desktopCapabilities: ["add_calendar_event"] },
  { message: "Dosyayı oku, analiz et, tablo çıkar", primaryIntent: "document", expectedFormat: "table", desktopCapabilities: ["document_read", "text_analyze", "spreadsheet_write"] },
  { message: "Araştır, analiz et, belge yaz ve kaydet", primaryIntent: "planning", expectedFormat: "docx", desktopCapabilities: ["web_research", "text_analyze", "document_write"] },
  { message: "Chrome'da sayfayı kaydır ve formu doldur", primaryIntent: "browser", desktopCapabilities: ["browser_control", "desktop_operator.run"] },
  { message: "Açık penceredeki hata mesajını oku ve çözüm öner", primaryIntent: "computer", desktopCapabilities: ["analyze_screen", "text_analyze"] },
  { message: "Bu sonucu sunuma dönüştür", primaryIntent: "document", expectedReference: "previous_answer", desktopCapabilities: ["presentation_write"] },
  { message: "Bu konuşmadan kısa görev özeti çıkar", primaryIntent: "writing", expectedReference: "previous_answer" },
];

test("dispatch quality matrix keeps 50 representative turns structured and backward-compatible", () => {
  assert.equal(scenarios.length, 50);
  for (const scenario of scenarios) {
    const envelope = buildTypedUnderstandingEnvelope({
      userId: "user_quality",
      message: scenario.message,
      metadata: scenario.metadata,
      intent: intent(scenario.primaryIntent),
    });

    assert.equal(envelope.schema_version, "2026-07-understanding-envelope-v2", scenario.message);
    assert.ok(envelope.intent_graph.nodes.length >= 1, scenario.message);
    assert.ok(envelope.privacy_routing.internalProviderDisclosure === "forbidden", scenario.message);
    assert.equal(envelope.privacy_routing.visibleProviderNamesAllowed, true, scenario.message);
    if (scenario.expectedReference) {
      assert.equal(envelope.source_reference, scenario.expectedReference, scenario.message);
      assert.equal(envelope.conversation_state.carryForward, true, scenario.message);
    }
    if (scenario.expectedFormat) {
      assert.equal(envelope.output_contract?.outputFormat, scenario.expectedFormat, scenario.message);
    }
    if (scenario.desktopCapabilities) {
      const workOrder = buildDesktopWorkOrder({
        message: scenario.message,
        title: "Quality matrix",
        routeDecision: route(scenario.desktopCapabilities),
        requestedCapabilities: scenario.desktopCapabilities,
        understandingEnvelope: envelope,
      });
      assert.equal(workOrder.schema, "elyan.desktop_work_order.v1", scenario.message);
      assert.equal(workOrder.execution.approvalPolicy, "single_full_access_surface", scenario.message);
      assert.ok(workOrder.contextPack, scenario.message);
      assert.ok(workOrder.executionPlan, scenario.message);
      assert.ok(workOrder.verificationPlan?.noModelClaimCompletion, scenario.message);
      assert.equal(workOrder.permissionEnvelope?.mode, "single_full_access_surface", scenario.message);
    }
  }
});
