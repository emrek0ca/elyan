import test from "node:test";
import assert from "node:assert/strict";
import {
  buildDesktopWorkOrder,
  isDeterministicDesktopAppWorkOrder,
  isDeterministicDesktopFastWorkOrder,
  isDesktopPlanPreparationPending,
  parseDirectDesktopAppCommand,
  parseDirectImageFetchCommand,
} from "./desktop-work-order.js";
import type { CommandRouteDecision } from "../routing-policy/service.js";
import type { UnderstandingEnvelope } from "../../core/understanding/types.js";
import type { RemoteMcpSelectionMetadata } from "../integrations/provider-registry.js";

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
  assert.equal(workOrder.workType, "screen_action");
  assert.equal(workOrder.execution.approvalPolicy, "single_full_access_surface");
  assert.equal(Array.isArray(workOrder.planPreview.liveNarrationPlan), true);
  assert.deepEqual(workOrder.planPreview.planPreparation, { status: "pending" });
});

test("desktop plan preparation gate blocks pending v1.7 work without an age escape", () => {
  const payload = {
    desktopWorkOrder: {
      planPreview: { planPreparation: { status: "pending" } },
    },
  };

  assert.equal(isDesktopPlanPreparationPending(payload), true);
  assert.equal(
    isDesktopPlanPreparationPending(
      {
        desktopWorkOrder: {
          planPreview: { planPreparation: { status: "ready" } },
        },
      },
    ),
    false,
  );
  assert.equal(isDesktopPlanPreparationPending({}), false);
});

test("buildDesktopWorkOrder carries safe quantum dispatch optimization hints", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Araştır, karşılaştır ve raporla.",
    title: "Dispatch kalite testi",
    routeDecision: routeDecision({ capabilities: ["web_research", "document_write"] }),
    requestedCapabilities: [],
    dispatchOptimization: {
      strategy: "quantum_guided_dispatch_v1",
      source: "backend_neural_readiness",
      active: true,
      score: 0.87,
      classicalBaselineScore: 0.73,
      advantageScore: 0.14,
      qualified: true,
      benchmarkSource: "measured",
      admissionWeight: 0.07,
      metric: "dispatch_schedule_quality",
    },
    responsiveExecution: {
      strategy: "quantum_liveness_guard_v1",
      source: "backend_neural_readiness",
      active: true,
      livenessScore: 0.82,
      qualified: true,
      benchmarkSource: "measured",
      boostWeight: 0.06,
      metric: "responsive_execution_liveness",
    },
    livenessGuard: {
      strategy: "quantum_replan_liveness_guard_v1",
      source: "backend_neural_readiness",
      active: true,
      timeoutRisk: "medium",
      maxReplans: 3,
      earlyProgressCheckpoint: true,
      safeStopOnTimeout: true,
      metric: "responsive_execution_liveness",
    },
  });

  assert.deepEqual(workOrder.planPreview.dispatchOptimization, {
    strategy: "quantum_guided_dispatch_v1",
    source: "backend_neural_readiness",
    active: true,
    score: 0.87,
    classicalBaselineScore: 0.73,
    advantageScore: 0.14,
    qualified: true,
    benchmarkSource: "measured",
    admissionWeight: 0.07,
    metric: "dispatch_schedule_quality",
  });
  assert.deepEqual(workOrder.planPreview.responsiveExecution, {
    strategy: "quantum_liveness_guard_v1",
    source: "backend_neural_readiness",
    active: true,
    livenessScore: 0.82,
    qualified: true,
    benchmarkSource: "measured",
    boostWeight: 0.06,
    metric: "responsive_execution_liveness",
  });
  assert.deepEqual(workOrder.planPreview.livenessGuard, {
    strategy: "quantum_replan_liveness_guard_v1",
    source: "backend_neural_readiness",
    active: true,
    timeoutRisk: "medium",
    maxReplans: 3,
    earlyProgressCheckpoint: true,
    safeStopOnTimeout: true,
    metric: "responsive_execution_liveness",
  });
});

test("buildDesktopWorkOrder keeps private file requests local and evidence-gated", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Masaüstündeki son PDF'i özetle.",
    title: "PDF özeti",
    routeDecision: routeDecision({ capabilities: ["document_read"] }),
    requestedCapabilities: [],
  });

  assert.equal(workOrder.localContextNeeded.includes("filesystem"), true);
  assert.equal(workOrder.requiredCapabilities.includes("document_read"), true);
  assert.equal(workOrder.requiredCapabilities.includes("filesystem_read"), false);
  assert.equal(workOrder.planPreview.privacyClass, "local_private");
  assert.equal(workOrder.verificationRules.some((rule) => rule.evidence === "tool_result"), true);
});

test("remote MCP work orders keep least-privilege scope and private routing", () => {
  const selection: RemoteMcpSelectionMetadata = {
    targetKind: "curated_app",
    appId: "github",
    connectionId: "conn_123",
    serverId: "app_github",
    operation: "read",
    confidence: 0.93,
    margin: 0.4,
    source: "explicit_name",
  };
  const workOrder = buildDesktopWorkOrder({
    message: "GitHub repolarımı göster",
    title: "GitHub repoları",
    routeDecision: routeDecision({ capabilities: ["mcp_call_tool"] }),
    requestedCapabilities: ["mcp_call_tool"],
    remoteMcpSelection: selection,
  });

  assert.deepEqual(workOrder.requiredCapabilities, ["mcp_call_tool"]);
  assert.deepEqual(workOrder.planPreview.steps, []);
  assert.deepEqual(workOrder.remoteMcp, selection);
  assert.equal(
    workOrder.requiredCapabilities.includes("desktop_operator.run"),
    false,
  );
  assert.equal(workOrder.planPreview.privacyClass, "local_private");
  assert.equal(workOrder.verificationRules.some((rule) => rule.id === "remote_mcp_tool_result"), true);
  assert.equal(workOrder.constraints.some((constraint) => constraint.includes("credentials never enter")), true);
});

test("remote MCP write work orders are side-effect scoped and require state readback", () => {
  const selection: RemoteMcpSelectionMetadata = {
    targetKind: "curated_app",
    appId: "slack",
    connectionId: "conn_write",
    serverId: "app_slack",
    operation: "write",
    confidence: 0.91,
    margin: 0.35,
    source: "semantic_transformer",
  };
  const workOrder = buildDesktopWorkOrder({
    message: "Slack çalışma alanımdaki proje kanalına durum mesajı gönder",
    title: "Slack mesajı",
    routeDecision: routeDecision({ capabilities: ["mcp_call_tool"] }),
    requestedCapabilities: ["mcp_call_tool"],
    remoteMcpSelection: selection,
  });

  assert.deepEqual(workOrder.requiredCapabilities, ["mcp_call_tool"]);
  assert.equal(workOrder.planPreview.privacyClass, "side_effect");
  assert.deepEqual(workOrder.planPreview.steps, []);
  assert.deepEqual(workOrder.remoteMcp, selection);
  assert.equal(
    workOrder.expectedOutputs.some((output) =>
      output.kind === "system_state" &&
      output.format === "remote_mcp_state_readback" &&
      output.required === true
    ),
    true,
  );
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
  assert.equal(presentation?.args.sourceContext, "Araştırma bağlamı: {{steps.step_web_research.output}}");
  assert.deepEqual(presentation?.dependsOn, ["step_web_research"]);
  assert.match(String(presentation?.args.prompt ?? ""), /5 slaytlık sunum/iu);
  assert.match(String(presentation?.args.outputPath ?? ""), /^~\/Desktop\/.+\.pptx$/u);
  assert.equal(workOrder.expectedOutputs.filter((output) => output.kind === "artifact").length, 1);
  assert.equal(workOrder.expectedOutputs.filter((output) => output.kind === "file_update").length, 1);
});

test("accounting KDV report includes calculation, research, analysis, and writer scope", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Muhasebeci gibi çalış. 12000 TL ve 8500 TL faturanın yüzde 20 KDV tutarını hesapla, KDV kurallarını araştır ve rapor hazırla.",
    title: "KDV raporu",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
  });

  assert.equal(workOrder.requiredCapabilities.includes("math_solve"), true);
  assert.equal(workOrder.requiredCapabilities.includes("web_research"), true);
  assert.equal(workOrder.requiredCapabilities.includes("text_analyze"), true);
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), true);
  assert.deepEqual(
    workOrder.planPreview.steps.map((step) => step.capability),
    ["web_research", "math_solve", "text_analyze", "document_write"],
  );
  const math = workOrder.planPreview.steps.find((step) => step.capability === "math_solve");
  assert.equal(math?.args.expression, "(12000+8500)*0.2");
  const analysis = workOrder.planPreview.steps.find((step) => step.capability === "text_analyze");
  assert.deepEqual(analysis?.dependsOn, ["step_web_research", "step_math_solve"]);
  assert.equal(analysis?.args.mode, "accounting");
  const writer = workOrder.planPreview.steps.find((step) => step.capability === "document_write");
  assert.deepEqual(writer?.dependsOn, ["step_text_analyze"]);
  assert.equal(writer?.args.sourceContext, "Analiz bağlamı: {{steps.step_text_analyze.output}}");
});

test("legal file workflow includes private read, public research, analysis, and defense writer", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Avukat gibi çalış. Bu dosya metnini analiz et: tahliye itirazı. Kira uyuşmazlığı mevzuatını araştır ve savunma dilekçesi hazırla.",
    title: "Savunma dilekçesi",
    routeDecision: routeDecision({ capabilities: ["document_read"] }),
    requestedCapabilities: [],
  });

  assert.equal(workOrder.requiredCapabilities.includes("document_read"), true);
  assert.equal(workOrder.requiredCapabilities.includes("web_research"), true);
  assert.equal(workOrder.requiredCapabilities.includes("text_analyze"), true);
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), true);
  assert.equal(workOrder.planPreview.privacyClass, "local_private");
  assert.deepEqual(
    workOrder.planPreview.steps.map((step) => step.capability),
    ["web_research", "document_read", "text_analyze", "document_write"],
  );
  const analysis = workOrder.planPreview.steps.find((step) => step.capability === "text_analyze");
  assert.deepEqual(analysis?.dependsOn, ["step_web_research", "step_document_read"]);
  assert.equal(analysis?.args.mode, "legal");
  assert.match(String(analysis?.args.sourceContext ?? ""), /Okunan bağlam/u);
  assert.match(String(analysis?.args.sourceContext ?? ""), /Araştırma bağlamı/u);
});

test("professional analysis mode follows medical student and technical domains", () => {
  const medical = buildDesktopWorkOrder({
    message: "Doktor gibi çalış. Tahlil sonuçlarını yorumla ve rapor çıkar: Hb 10.5, ferritin 8, B12 220.",
    title: "Tahlil raporu",
    routeDecision: routeDecision({ capabilities: ["document_read"] }),
    requestedCapabilities: [],
  });
  const student = buildDesktopWorkOrder({
    message: "Öğrenci gibi çalış. Kuantum annealing konusunu araştır, analiz et ve sunum hazırla.",
    title: "Öğrenci sunumu",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
  });
  const technical = buildDesktopWorkOrder({
    message: "Mühendis gibi çalış. Kapasite kısıtı olan optimizasyon problemini analiz et ve rapor hazırla.",
    title: "Optimizasyon raporu",
    routeDecision: routeDecision(),
    requestedCapabilities: [],
  });

  const medicalAnalysis = medical.planPreview.steps.find((step) => step.capability === "text_analyze");
  const studentAnalysis = student.planPreview.steps.find((step) => step.capability === "text_analyze");
  const technicalAnalysis = technical.planPreview.steps.find((step) => step.capability === "text_analyze");

  assert.equal(medicalAnalysis?.args.mode, "medical");
  assert.equal(studentAnalysis?.args.mode, "student");
  assert.equal(technicalAnalysis?.args.mode, "technical");
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
    intent_graph: {
      nodes: [{ id: "n1", kind: "write", label: "PDF üret", surface: "desktop", confidence: 0.9 }],
      edges: [],
    },
    source_reference: "previous_answer",
    latest_artifact_ref: { id: "artifact_1", kind: "document", summary: "Aylık gelir raporu" },
    conversation_state: {
      turnKind: "follow_up",
      currentGoal: "PDF yap",
      lastAssistantSummary: "Gelir raporu metni hazırlandı.",
      lastArtifactSummary: "Gelir raporu",
      lastImagePrompt: null,
      userCorrection: null,
      carryForward: true,
    },
    entities: [{ type: "amount", value: "12000", normalized: "12000", confidence: 0.98, source: "typed_extractor" }],
    constraints: [{ kind: "footer_text", value: "Emre", confidence: 0.99, source: "typed_extractor", explicit: true }],
    desired_outputs: [{ kind: "pdf", format: "pdf", target: "artifact", confidence: 0.99, constraints: ["footer_text"] }],
    success_criteria: [{ kind: "footer_preserved", description: "Footer en altta olmalı.", evidenceRequired: "artifact", confidence: 0.95 }],
    ambiguities: [],
    ambiguity_policy: {
      action: "proceed_with_best_reference",
      reason: "follow_up_reference_resolved",
      assumedReference: "previous_answer",
    },
    risk: { privacy: "low", safety: "low", cost: "low", latency: "low", local_private: false, side_effect: false, prompt_injection: false, reasons: [] },
    privacy_routing: {
      mode: "server",
      mayUseHostedModels: true,
      maySendPrivateContextToServer: false,
      reasons: ["server_safe_context"],
    },
    required_capabilities: [{ name: "document.write", executionSurface: "desktop", permission: "write", confidence: 0.96 }],
    tool_skill_decision: {
      selected: "document.write",
      surface: "document",
      workload: "document_generate",
      confidence: 0.92,
      reasons: ["document_artifact_surface"],
      candidates: [],
    },
    output_contract: {
      operation: "export",
      sourceReference: "previous_answer",
      outputKind: "document",
      outputFormat: "pdf",
      pageCount: null,
      requiresArtifact: true,
      confidence: 0.9,
      reasons: ["format:pdf"],
    },
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
  assert.equal(workOrder.contextPack?.sourceReference, "previous_answer");
  assert.equal(workOrder.contextPack?.latestArtifactRef?.id, "artifact_1");
  assert.equal(workOrder.executionPlan?.planner, "server_brain");
  assert.equal(workOrder.permissionEnvelope?.mode, "single_full_access_surface");
  assert.equal(workOrder.understanding?.conversationState?.carryForward, true);
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), true);
  assert.equal(workOrder.requiredCapabilities.includes("canvas_write"), false);
  assert.equal(
    workOrder.planPreview.steps.filter(
      (step) =>
        step.capability === "document_write" ||
        step.capability === "canvas_write",
    ).length,
    1,
  );
  assert.equal("message" in workOrder, false);
  assert.equal("prompt" in workOrder, false);
});

test("buildDesktopWorkOrder plans research to desktop document from semantic envelope", () => {
  const envelope: UnderstandingEnvelope = {
    schema_version: "2026-07-understanding-envelope-v2",
    intent: {
      name: "research",
      action: "create_study_guide",
      topic: "Ceza hukuku çalışma rehberi",
      confidence: 0.97,
      source: "typed_extractor",
    },
    intent_graph: {
      nodes: [
        { id: "gather", kind: "gather", label: "Güvenilir kaynakları topla", surface: "server", confidence: 0.9 },
        { id: "analyze", kind: "analyze", label: "Öğrenci düzeyinde analiz et", surface: "desktop", confidence: 0.9 },
        { id: "write", kind: "write", label: "DOCX belge yaz", surface: "desktop", confidence: 0.95 },
        { id: "verify", kind: "verify", label: "Dosya kanıtını doğrula", surface: "desktop", confidence: 0.95 },
      ],
      edges: [
        { from: "gather", to: "analyze", reason: "research feeds analysis" },
        { from: "analyze", to: "write", reason: "analysis feeds document" },
      ],
    },
    source_reference: "current_prompt",
    latest_artifact_ref: null,
    conversation_state: {
      turnKind: "new_request",
      currentGoal: "Ceza hukuku rehberi oluştur",
      lastAssistantSummary: null,
      lastArtifactSummary: null,
      lastImagePrompt: null,
      userCorrection: null,
      carryForward: false,
    },
    entities: [{ type: "topic", value: "Ceza hukuku", normalized: "Ceza hukuku", confidence: 0.98, source: "typed_extractor" }],
    constraints: [
      { kind: "language", value: "tr", confidence: 0.9, source: "typed_extractor", explicit: true },
      { kind: "document_kind", value: "study_guide", confidence: 0.9, source: "typed_extractor", explicit: true },
    ],
    desired_outputs: [{ kind: "docx", format: "docx", target: "desktop", confidence: 0.98, constraints: ["study_guide"] }],
    success_criteria: [
      { kind: "artifact_verified", description: "DOCX dosyası artifact/state_readback kanıtıyla doğrulanmalı.", evidenceRequired: "artifact", confidence: 0.96 },
    ],
    ambiguities: [],
    ambiguity_policy: { action: "proceed_with_best_reference", reason: "explicit_topic_and_output", assumedReference: "current_prompt" },
    risk: { privacy: "low", safety: "low", cost: "low", latency: "medium", local_private: false, side_effect: true, prompt_injection: false, reasons: ["desktop_artifact_write"] },
    privacy_routing: {
      mode: "desktop_private",
      mayUseHostedModels: true,
      maySendPrivateContextToServer: false,
      reasons: ["desktop_artifact_execution"],
    },
    required_capabilities: [
      { name: "document.write", executionSurface: "desktop", permission: "write", confidence: 0.98 },
    ],
    tool_skill_decision: {
      selected: "document.write",
      surface: "document",
      workload: "desktop_handoff",
      confidence: 0.95,
      reasons: ["verified_desktop_artifact"],
      candidates: [],
    },
    output_contract: {
      operation: "export",
      sourceReference: "current_prompt",
      outputKind: "document",
      outputFormat: "docx",
      pageCount: null,
      requiresArtifact: true,
      confidence: 0.97,
      reasons: ["docx_desktop_artifact"],
    },
    memory_candidates: [],
    confidence: 0.97,
    source: "typed_extractor",
  };

  const workOrder = buildDesktopWorkOrder({
    message:
      "Ceza hukuku nedir araştır ve öğrenci için DOCX çalışma rehberi olarak masaüstüne kaydet.",
    title: "Ceza hukuku rehberi",
    routeDecision: routeDecision({ capabilities: [] }),
    requestedCapabilities: [],
    understandingEnvelope: envelope,
  });

  const capabilities = workOrder.planPreview.steps.map((step) => step.capability);
  assert.deepEqual(capabilities.slice(0, 3), [
    "web_research",
    "text_analyze",
    "document_write",
  ]);
  assert.equal(workOrder.semanticGoal?.contract, "elyan.semantic_task_contract.v1");
  assert.equal(workOrder.workType, "data_workflow");
  assert.equal(workOrder.expectedOutputs.some((output) => output.kind === "artifact"), true);
  assert.equal(workOrder.verificationPlan?.requireEvidence, true);
  assert.equal(workOrder.planPreview.privacyClass, "side_effect");
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

test("write destination does not grant an unrelated private document read", () => {
  const workOrder = buildDesktopWorkOrder({
    message: "Raporu masaüstüne kaydet",
    title: "Rapor",
    routeDecision: routeDecision({ capabilities: [] }),
    requestedCapabilities: [],
  });
  assert.equal(workOrder.requiredCapabilities.includes("document_read"), false);
  assert.equal(workOrder.requiredCapabilities.includes("document_write"), true);
  assert.equal(
    workOrder.expectedOutputs.some((output) => output.kind === "artifact"),
    true,
  );
});

test("semantic document intent reconciles a stale chat output contract", () => {
  const envelope: UnderstandingEnvelope = {
    schema_version: "2026-07-understanding-envelope-v2",
    intent: {
      name: "document",
      action: "reply",
      topic: "Tarihsel yaşam öyküsü",
      confidence: 0.82,
      source: "semantic_classifier",
    },
    intent_graph: { nodes: [], edges: [] },
    source_reference: "current_prompt",
    latest_artifact_ref: null,
    conversation_state: {
      turnKind: "new_request",
      currentGoal: "Tarihsel yaşam öyküsünü iki sayfalık çıktı olarak teslim et",
      lastAssistantSummary: null,
      lastArtifactSummary: null,
      lastImagePrompt: null,
      userCorrection: null,
      carryForward: false,
    },
    entities: [],
    constraints: [],
    desired_outputs: [
      {
        kind: "chat_reply",
        format: null,
        target: "chat",
        confidence: 0.82,
        constraints: [],
      },
    ],
    success_criteria: [],
    ambiguities: [],
    ambiguity_policy: {
      action: "proceed_with_best_reference",
      reason: "current_prompt_is_best_reference",
      assumedReference: "current_prompt",
    },
    risk: {
      privacy: "low",
      safety: "low",
      cost: "low",
      latency: "low",
      local_private: false,
      side_effect: false,
      prompt_injection: false,
      reasons: [],
    },
    privacy_routing: {
      mode: "server",
      mayUseHostedModels: true,
      maySendPrivateContextToServer: false,
      reasons: ["server_safe_context"],
    },
    required_capabilities: [],
    tool_skill_decision: {
      selected: "chat.reply",
      surface: "chat",
      workload: null,
      confidence: 0.74,
      reasons: ["default_chat_surface"],
      candidates: [],
    },
    output_contract: {
      operation: "answer",
      sourceReference: "current_prompt",
      outputKind: "chat_reply",
      outputFormat: null,
      pageCount: 2,
      requiresArtifact: false,
      confidence: 0.52,
      reasons: ["operation:answer"],
    },
    memory_candidates: [],
    confidence: 0.615,
    source: "typed_extractor",
  };

  const workOrder = buildDesktopWorkOrder({
    message: "Tarihsel yaşam öyküsünü iki sayfalık çıktı olarak teslim et",
    title: "Yaşam öyküsü",
    routeDecision: routeDecision({ capabilities: ["document_write"] }),
    requestedCapabilities: [],
    understandingEnvelope: envelope,
  });

  assert.deepEqual(workOrder.requiredCapabilities, ["document_write"]);
  assert.equal(workOrder.contextPack?.outputContract?.requiresArtifact, true);
  assert.equal(workOrder.contextPack?.outputContract?.outputFormat, "docx");
  assert.equal(
    workOrder.contextPack?.toolSkillDecision?.selected,
    "document.write",
  );
  assert.equal(workOrder.contextPack?.privacyRouting?.mode, "desktop_private");
  assert.deepEqual(workOrder.resourceScope, {
    contract: "elyan.resource_scope.v1",
    readRoots: ["workspace"],
    writeRoots: ["~/Desktop"],
  });
  assert.match(
    String(workOrder.planPreview.steps[0]?.args.outputPath ?? ""),
    /^~\/Desktop\/.+\.docx$/u,
  );
  assert.equal(
    workOrder.understanding?.desiredOutputs.some(
      (output) => output.target === "desktop" && output.format === "docx",
    ),
    true,
  );

  const pdfEnvelope = structuredClone(envelope);
  pdfEnvelope.desired_outputs = [
    {
      kind: "pdf",
      format: "pdf",
      target: "desktop",
      confidence: 0.9,
      constraints: [],
    },
  ];
  pdfEnvelope.output_contract = {
    ...pdfEnvelope.output_contract!,
    operation: "write",
    outputKind: "document",
    outputFormat: "pdf",
    requiresArtifact: true,
    confidence: 0.9,
  };
  const pdfWorkOrder = buildDesktopWorkOrder({
    message: "Tarihsel yaşam öyküsünü iki sayfalık PDF olarak teslim et",
    title: "Yaşam öyküsü PDF",
    routeDecision: routeDecision({
      capabilities: ["document_write", "canvas_write"],
    }),
    requestedCapabilities: [],
    understandingEnvelope: pdfEnvelope,
  });
  assert.deepEqual(pdfWorkOrder.requiredCapabilities, ["document_write"]);
  assert.equal(
    pdfWorkOrder.planPreview.steps.filter(
      (step) =>
        step.capability === "document_write" ||
        step.capability === "canvas_write",
    ).length,
    1,
  );
  assert.match(
    String(pdfWorkOrder.planPreview.steps[0]?.args.outputPath ?? ""),
    /\.pdf$/u,
  );
});
