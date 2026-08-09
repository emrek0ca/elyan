import test from "node:test";
import assert from "node:assert/strict";
import {
  buildMaterializedPlanResponseSchema,
  buildAllowedCapabilities,
  buildPlanningPrompt,
  clearPlanningCatalogCacheForTests,
  compileValidatedSemanticFallback,
  getPlanningCatalogCacheStats,
  markDesktopPlanPrepared,
  maybeMaterializeDesktopPlan,
  MATERIALIZE_PROMPT_MAX_BYTES,
  normalizeMaterializedSteps,
  readPlanningGatePrompt,
  renderPlanningFewShots,
  validateMaterializedPlanAgainstWorkOrder,
  validateMaterializedPlanContracts,
} from "./materialize-plan.js";
import type { DesktopWorkOrder } from "./desktop-work-order.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";

function workOrder(
  summary: string,
  requiredCapabilities = ["math_solve", "web_research", "text_analyze", "document_write", "spreadsheet_write", "presentation_write"],
): DesktopWorkOrder {
  return {
    schema: "elyan.desktop_work_order.v1",
    source: "mobile_chat_dispatch",
    goal: {
      kind: "desktop_cowork",
      summary,
      language: "tr",
      sourceTextHash: "0".repeat(24),
    },
    entities: [],
    constraints: [],
    requiredCapabilities,
    localContextNeeded: [],
    expectedOutputs: [{ kind: "artifact", format: "docx", required: true }],
    verificationRules: [{ id: "artifact", description: "Çıktı üretildi.", evidence: "artifact" }],
    execution: {
      mode: "cowork_dispatch",
      approvalPolicy: "capability_policy",
      maxSteps: 16,
    },
    planPreview: {
      summary,
      privacyClass: "local_private",
      steps: [],
    },
  };
}

test("an already materialized server plan remains dispatchable on retry", async () => {
  const order = workOrder("Masaüstünü listele", ["directory_tree"]);
  order.planPreview = {
    ...order.planPreview,
    planSource: "server_materialized",
    contract: "elyan.compiled_plan.v1",
    steps: [
      {
        id: "list",
        capability: "directory_tree",
        description: "Masaüstünü listele",
        args: { path: "~/Desktop" },
      },
    ],
  };
  order.materializedCapabilityScope = ["directory_tree"];
  const task = {
    id: "task-retry-ready-plan",
    userId: "user-1",
    payload: { desktopWorkOrder: order },
  };

  const materialized = await maybeMaterializeDesktopPlan(
    { log: { warn() { throw new Error("retry must not invoke planning"); } } } as never,
    task as never,
  );

  assert.equal(materialized, true);
});

test("a semantic server plan without a current binding is rematerialized", async () => {
  const order = workOrder("Masaüstünü listele", ["directory_tree"]);
  order.semanticGoal = {
    contract: "elyan.semantic_task_contract.v1",
    objective: "Masaüstünü listele",
    constraints: [],
    successCriteria: ["Liste döner."],
    requiredCapabilities: ["directory_tree"],
    forbiddenCapabilities: [],
    ambiguityPolicy: "safe_assumption",
    risk: {
      localPrivate: true,
      sideEffect: false,
      irreversible: false,
    },
  };
  order.planPreview = {
    ...order.planPreview,
    planSource: "server_materialized",
    contract: "elyan.compiled_plan.v1",
    steps: [
      {
        id: "list",
        capability: "directory_tree",
        description: "Masaüstünü listele",
        args: { path: "~/Desktop" },
      },
    ],
  };

  assert.equal(
    await maybeMaterializeDesktopPlan(
      { log: { info() {}, warn() {} } } as never,
      {
        id: "task-unbound-semantic-plan",
        userId: "user-1",
        payload: { desktopWorkOrder: order },
      } as never,
    ),
    false,
  );
});

test("an incomplete server-plan marker fails closed on retry", async () => {
  const order = workOrder("Masaüstünü listele", ["directory_tree"]);
  order.planPreview = {
    ...order.planPreview,
    planSource: "server_materialized",
    steps: [
      {
        id: "list",
        capability: "directory_tree",
        description: "Masaüstünü listele",
        args: {},
      },
    ],
  };

  assert.equal(
    await maybeMaterializeDesktopPlan(
      { log: { warn() {} } } as never,
      {
        id: "task-retry-invalid-plan",
        userId: "user-1",
        payload: { desktopWorkOrder: order },
      } as never,
    ),
    false,
  );
});

test("semantic privacy authority bounds model capabilities without keyword scope", () => {
  const publicOrder = workOrder("Yerel bir hesap yap", ["file_read"]);
  publicOrder.capabilityAuthorization = {
    source: "semantic_router",
    allowPrivateRead: false,
    sideEffectsRequireApproval: true,
  };
  // `requiredCapabilities` artık BEYAZ LİSTE değil İPUCUDUR: planlayıcı doğru
  // aracı seçebilmeli (yanlış tahmin görevi komple çökertmemeli). Bu testin
  // koruduğu şey kapsam darlığı değil, GİZLİLİK YETKİSİ — o aynen sürüyor.
  const publicAllowed = buildAllowedCapabilities(publicOrder);
  assert.equal(publicAllowed.includes("file_read"), false);

  publicOrder.capabilityAuthorization.allowPrivateRead = true;
  const readAllowed = buildAllowedCapabilities(publicOrder);
  assert.equal(readAllowed.includes("file_read"), true);
  // İpucu olarak verilen yetenek listenin BAŞINDA gelir (öncelik korunur).
  assert.equal(readAllowed[0], "file_read");

  const writerOrder = workOrder("Yerel belge üret", ["document_write"]);
  writerOrder.capabilityAuthorization = {
    source: "semantic_router",
    allowPrivateRead: false,
    sideEffectsRequireApproval: true,
  };
  const writerAllowed = buildAllowedCapabilities(writerOrder);
  assert.equal(writerAllowed[0], "document_write");
  // Gizlilik yetkisi kapalıyken özel-okuma sınıfı yetenek sızmamalı.
  assert.equal(writerAllowed.includes("file_read"), false);
});

test("planning safety gate inspects the real user goal, not the capability catalog", () => {
  const order = workOrder("Fallback summary");
  order.contextPack = {
    sourceReference: "current_prompt",
    conversationState: {
      currentGoal: "Masaüstü klasörümü listele",
    },
  };

  assert.equal(readPlanningGatePrompt(order), "Masaüstü klasörümü listele");
  const prompt = buildPlanningPrompt(order, ["directory_tree"]);
  assert.match(prompt, /GOAL:\nMasaüstü klasörümü listele/);
  assert.doesNotMatch(prompt, /GOAL:\nFallback summary/);
  delete order.contextPack;
  assert.equal(readPlanningGatePrompt(order), "Fallback summary");
});

test("desktop materialization prompt teaches concrete calculation research writer chains", () => {
  const prompt = buildPlanningPrompt(
    workOrder(
      "Muhasebeci gibi çalış. 12000 TL ve 8500 TL hizmet faturası için yüzde 20 KDV hesapla, KDV kurallarını araştır ve rapor hazırla.",
    ),
    ["math_solve", "web_research", "text_analyze", "document_write", "spreadsheet_write", "presentation_write"],
  );

  assert.match(prompt, /Accounting calculation \+ research \+ report/);
  assert.match(prompt, /"expression":"\(12000\+8500\)\*0\.20"/);
  assert.match(prompt, /"query":"hizmet faturasi KDV yuzde 20 kurallari Turkiye"/);
  assert.match(prompt, /"capability":"text_analyze"/);
  assert.match(prompt, /"sourceContext":"KDV hesabi: \{\{steps\.s1\.output\}\}\\n\\nArastirma: \{\{steps\.s2\.output\}\}"/);
  assert.match(prompt, /"content":"KDV hesabi: \{\{steps\.s1\.output\}\}\\n\\nArastirma: \{\{steps\.s2\.output\}\}\\n\\nAnaliz: \{\{steps\.s3\.output\}\}"/);
  assert.match(prompt, /tax amount.*\(12000\+8500\)\*0\.20/i);
  assert.match(prompt, /tax-included total.*\(12000\+8500\)\*1\.20/i);
  assert.match(prompt, /professional chain/);
  assert.match(prompt, /Full Computer Access/);
  assert.match(prompt, /verified/i);
});

test("desktop materialization prompt carries context pack for follow-up artifact transforms", () => {
  const order = workOrder("Bunu PDF yap", ["document_write", "text_analyze"]);
  order.contextPack = {
    sourceReference: "latest_artifact",
    conversationState: {
      turnKind: "follow_up",
      carryForward: true,
      lastAssistantSummary: "Diferansiyel geometri kullanım alanları metni hazırlandı.",
    },
    latestArtifactRef: {
      id: "artifact_geo_1",
      kind: "text",
      summary: "Diferansiyel geometri kullanım alanları",
    },
    outputContract: {
      operation: "export",
      sourceReference: "latest_artifact",
      outputKind: "document",
      outputFormat: "pdf",
      requiresArtifact: true,
      confidence: 0.92,
    },
    toolSkillDecision: {
      selected: "document.write",
      surface: "document",
      confidence: 0.9,
    },
    privacyRouting: {
      mode: "server",
    },
  };

  const prompt = buildPlanningPrompt(order, ["document_write", "text_analyze"]);

  assert.match(prompt, /UNDERSTANDING CONTEXT/);
  assert.match(prompt, /sourceReference: latest_artifact/);
  assert.match(prompt, /artifact_geo_1/);
  assert.match(prompt, /conversationState\.turnKind=correction|turnKind=correction|turnKind/);
  assert.match(prompt, /Bunu PDF yap/);
  assert.match(prompt, /Do not start an unrelated new topic/);
  assert.match(prompt, /PDF\/DOCX\/XLSX\/image\/chart requests must produce a matching artifact step/);
});

test("desktop materialization keeps full catalog awareness but expands only required capability contracts", () => {
  const order = workOrder("Bir rapor hazırla", ["document_write"]);
  const prompt = buildPlanningPrompt(order, [
    "document_write",
    "spreadsheet_write",
    "open_app",
    "run_skill",
  ]);

  const documentLine = prompt
    .split("\n")
    .find((line) => line.startsWith("- document_write:"));
  const spreadsheetLine = prompt
    .split("\n")
    .find((line) => line.startsWith("- spreadsheet_write:"));
  assert.match(documentLine ?? "", /\| input:/);
  assert.ok(spreadsheetLine);
  assert.doesNotMatch(spreadsheetLine ?? "", /\| input:/);
  assert.match(prompt, /open_app:/);
  assert.ok(prompt.length < 50_000);
});

test("desktop materialization prompt keeps research queries public and writer args contextual", () => {
  const fewShots = renderPlanningFewShots();

  assert.match(fewShots, /Legal research \+ defense draft/);
  assert.match(fewShots, /kira uyusmazligi tahliye davasi savunma dilekcesi mevzuat emsal/);
  assert.match(fewShots, /"prompt":"Arastirma sonucunu savunma dilekcesi icin hukuki arguman ve riskler acisindan analiz et"/);
  assert.match(fewShots, /"sourceContext":"Arastirma: \{\{steps\.s1\.output\}\}"/);
  assert.match(fewShots, /"content":"Arastirma: \{\{steps\.s1\.output\}\}\\n\\nAnaliz: \{\{steps\.s2\.output\}\}/);
  assert.match(fewShots, /Legal private file \+ public research \+ defense draft/);
  assert.match(fewShots, /"capability":"document_read"/);
  assert.match(fewShots, /"query":"kira uyusmazligi tahliye itirazi savunma dilekcesi mevzuat emsal"/);
  assert.match(fewShots, /"capability":"text_analyze"/);
  assert.match(fewShots, /Dosya baglami: \{\{steps\.s1\.output\}\}\\n\\nPublic arastirma: \{\{steps\.s2\.output\}\}/);
  assert.match(fewShots, /Analiz: \{\{steps\.s3\.output\}\}/);
  assert.match(fewShots, /Private inline data \+ analysis report/);
  assert.match(fewShots, /"capability":"document_read"/);
  assert.match(fewShots, /Hb 10\.5, ferritin 8, B12 220/);
  assert.match(fewShots, /"sourceContext":"Veri: \{\{steps\.s1\.output\}\}"/);
  assert.match(fewShots, /"content":"Okunan veri uzerinden analiz raporu hazirla\.\\n\\nVeri: \{\{steps\.s1\.output\}\}\\n\\nAnaliz: \{\{steps\.s2\.output\}\}"/);
  assert.match(fewShots, /Student research \+ presentation/);
  assert.match(fewShots, /quantum annealing vs classical optimization explanation examples/);
  assert.match(fewShots, /"capability":"text_analyze"/);
  assert.match(fewShots, /"mode":"student"/);
  assert.match(fewShots, /"sourceContext":"Arastirma: \{\{steps\.s1\.output\}\}"/);
  assert.match(fewShots, /Analiz: \{\{steps\.s2\.output\}\}\\n\\nArastirma: \{\{steps\.s1\.output\}\}/);
  assert.match(fewShots, /Research \+ spreadsheet/);
  assert.match(fewShots, /"capability":"spreadsheet_write"/);
  assert.match(fewShots, /"KDV tutari","\{\{steps\.s1\.output\}\}"/);
  assert.match(fewShots, /Optimization decision support/);
  assert.match(fewShots, /quantum_model_problem/);
  assert.match(fewShots, /quantum_run_experiment/);
  assert.match(fewShots, /quantum_compare_classical/);
  assert.match(fewShots, /quantum_generate_report/);

  const prompt = buildPlanningPrompt(
    workOrder("Avukat gibi çalış. Dosya özeti özel kalsın; kira uyuşmazlığını araştır ve savunma dilekçesi hazırla."),
    ["web_research", "document_write"],
  );

  assert.match(prompt, /Do not pass the full user goal, private case facts, file summaries, or writing instructions as the query/);
  assert.match(prompt, /preserve private case\/test\/project facts in writer args/);
});

test("desktop materialization prompt teaches output artifact target selection", () => {
  const prompt = buildPlanningPrompt(
    workOrder(
      "Öğrenci gibi çalış. Kuantum annealing konusunu araştır ve 5 sayfalık sunum hazırla.",
      ["web_research", "presentation_write", "document_write", "spreadsheet_write"],
    ),
    ["web_research", "presentation_write", "document_write", "spreadsheet_write"],
  );

  assert.match(prompt, /Excel\/table\/spreadsheet\/xlsx -> spreadsheet_write/);
  assert.match(prompt, /presentation\/slides\/pptx -> presentation_write/);
  assert.match(prompt, /Word\/report\/petition\/document\/docx -> document_write/);
  assert.match(prompt, /Do not use document_write for a requested presentation or spreadsheet/);
  assert.match(prompt, /For presentation_write, provide a concrete title and prompt\/content that consumes research\/read outputs/);
  assert.match(prompt, /analyze\/interpret\/evaluate\/summarize\/explain\/compare or produce a professional\/student artifact/);
  assert.match(prompt, /For spreadsheet_write, provide concrete rows\/sheets/);
});

test("desktop materialization prompt exposes skills through run_skill contract", () => {
  const prompt = buildPlanningPrompt(
    workOrder(
      "Verilen analiz sonucundan profesyonel DOCX raporu hazırla ve kaydet.",
      ["text_analyze", "run_skill", "document_write"],
    ),
    ["text_analyze", "run_skill", "document_write"],
  );

  assert.match(prompt, /TOOL CAPABILITY CATALOG/);
  assert.match(prompt, /SKILL CATALOG/);
  assert.match(prompt, /document\.docx_from_context/);
  assert.match(prompt, /execute them ONLY through capability run_skill with args\.skillId and args\.payload/);
  assert.match(prompt, /capability":"run_skill"/);
  assert.match(prompt, /"skillId":"document\.docx_from_context"/);
  assert.match(prompt, /"payload":\{"title":"Profesyonel Rapor","text":"\{\{steps\.s1\.output\}\}","outputPath":"workspace\/Profesyonel Rapor\.docx"\}/);
  assert.match(prompt, /Do not invent capability names from skill ids/);
});

test("desktop materialization prompt exposes v2 capability quality contracts", () => {
  const prompt = buildPlanningPrompt(
    workOrder(
      "Ekranı oku, sonra bu konuşmayı PDF yap ve gerekirse Excel tablosuna dönüştür.",
      [
        "analyze_screen",
        "desktop_operator.observe_screen",
        "desktop_operator.run",
        "canvas_write",
        "spreadsheet_write",
        "document_write",
        "run_skill",
      ],
    ),
    [
      "analyze_screen",
      "desktop_operator.observe_screen",
      "desktop_operator.run",
      "canvas_write",
      "spreadsheet_write",
      "document_write",
      "run_skill",
    ],
  );

  assert.match(prompt, /canvas_write: PDF\/PNG canvas çıktısı üretir/);
  assert.match(prompt, /artifact: .*"artifactTypes":\["pdf","image"\]/);
  assert.match(prompt, /spreadsheet_write: XLSX\/Excel çalışma kitabı üretir/);
  assert.match(prompt, /output: .*"formats":\["xlsx"\]/);
  assert.match(prompt, /analyze_screen: Aktif pencereyi kullanıcı sorusuna göre görsel olarak analiz eder/);
  assert.match(prompt, /privacy: local_private_screen/);
  assert.match(prompt, /desktop_operator\.run: Çok adımlı observe→decide→act→verify ekran otomasyonu hedefini yürütür/);
  assert.match(prompt, /verify: .*Operator loop must stop on success/);
  assert.match(prompt, /input: .*"skillIdMustExistInCatalog":true/);
});

test("desktop materialization prompt teaches data versus screen action plan modes", () => {
  const prompt = buildPlanningPrompt(
    workOrder(
      "Chrome'u aç, yeni sekme aç, ekrandaki arama kutusuna kuantum optimizasyon yaz ve sonucu kontrol et.",
      [
        "open_app",
        "browser_control",
        "desktop_operator.observe_screen",
        "desktop_operator.execute_action",
        "desktop_operator.run",
        "close_app",
      ],
    ),
    [
      "open_app",
      "browser_control",
      "desktop_operator.observe_screen",
      "desktop_operator.execute_action",
      "desktop_operator.run",
      "close_app",
    ],
  );

  assert.match(prompt, /PLAN MODE DECISION/);
  assert.match(prompt, /DATA WORKFLOW/);
  assert.match(prompt, /SCREEN-ACTION WORKFLOW/);
  assert.match(prompt, /Screen-action workflow/);
  assert.match(prompt, /"capability":"open_app"/);
  assert.match(prompt, /"action":"new_tab"/);
  assert.match(prompt, /"capability":"desktop_operator\.observe_screen"/);
  assert.match(prompt, /"capability":"desktop_operator\.execute_action"/);
  assert.match(prompt, /"action":"type","text":"kuantum optimizasyon"/);
  assert.match(prompt, /"action":"press","key":"ENTER"/);
  assert.match(prompt, /Screen-action delegated loop/);
  assert.match(prompt, /"capability":"desktop_operator\.run"/);
  assert.match(prompt, /observe -> decide -> act/);
  assert.match(prompt, /Verify important UI state with desktop_operator\.observe_screen after actions/);
});

test("desktop materialization prompt hides skill execution when run_skill is not allowed", () => {
  const prompt = buildPlanningPrompt(
    workOrder("Kısa araştırma raporu hazırla.", ["web_research", "document_write"]),
    ["web_research", "document_write"],
  );

  assert.match(prompt, /SKILL CATALOG/);
  assert.match(prompt, /\(run_skill is not allowed for this work order\)/);
});

test("desktop materialization prompt teaches private read then writer handoff", () => {
  const prompt = buildPlanningPrompt(
    workOrder(
      "Doktor gibi çalış. Tahlil sonuçlarını yorumla ve rapor çıkar: Hb 10.5, ferritin 8, B12 220.",
      ["document_read", "document_write", "web_research"],
    ),
    ["document_read", "document_write", "web_research"],
  );

  assert.match(prompt, /Private inline data \+ analysis report/);
  assert.match(prompt, /start with document_read or file_read when available/);
  assert.match(prompt, /insert text_analyze between gathering\/calculation\/research and the writer/);
  assert.match(prompt, /feed \{\{steps\.<id>\.output\}\} into document_write/);
  assert.match(prompt, /Do not send private inline facts, file contents, medical\/test values, legal case facts, or local document summaries to web_research/);
  assert.match(prompt, /"text":"Tahlil sonuclari: Hb 10\.5, ferritin 8, B12 220\."/);
});

test("desktop materialization prompt teaches decision support optimization chain", () => {
  const prompt = buildPlanningPrompt(
    workOrder(
      "Karar destek ajanı gibi çalış. A değer 10 maliyet 4, B değer 7 maliyet 3, C değer 12 maliyet 8; kapasite 10. Problemi karar değişkenleri, amaç fonksiyonu ve kısıtlarla modelle, çöz ve uygulanabilirliği doğrula.",
    ),
    [
      "quantum_model_problem",
      "quantum_run_experiment",
      "quantum_compare_classical",
      "quantum_generate_report",
    ],
  );

  assert.match(prompt, /Optimization decision support/);
  assert.match(prompt, /decision-support chain: quantum_model_problem -> quantum_run_experiment -> quantum_compare_classical -> quantum_generate_report/);
  assert.match(prompt, /A deger 10 maliyet 4/);
  assert.match(prompt, /"problemClass":"optimization"/);
  assert.match(prompt, /"prompt":"\{\{steps\.s1\.output\}\}"/);
  assert.match(prompt, /Model: \{\{steps\.s1\.output\}\}\\n\\nCozum: \{\{steps\.s2\.output\}\}\\n\\nDogrulama: \{\{steps\.s3\.output\}\}/);
});

test("desktop materialization normalizer rejects non-catalog capabilities", () => {
  const steps = normalizeMaterializedSteps(
    {
      steps: [
        {
          id: "s1",
          capability: "web_research",
          args: { query: "public KDV kurallari" },
          dependsOn: [],
          description: "Araştır",
        },
        {
          id: "s2",
          capability: "private_file_upload",
          args: { path: "/tmp/secret.pdf" },
          dependsOn: ["s1"],
          description: "Katalog dışı adım",
        },
        {
          id: "s3",
          capability: "document_write",
          args: { content: "{{steps.s1.output}}" },
          dependsOn: ["s1"],
          description: "Rapor yaz",
        },
      ],
    },
    ["web_research", "document_write"],
  );

  assert.deepEqual(
    steps?.map((step) => step.capability),
    ["web_research", "document_write"],
  );
});

test("desktop materialization normalizer infers dependencies from step templates", () => {
  const steps = normalizeMaterializedSteps(
    {
      steps: [
        {
          id: "s1",
          capability: "web_research",
          args: { query: "public KDV kurallari" },
          dependsOn: [],
          description: "Araştır",
        },
        {
          id: "s2",
          capability: "text_analyze",
          args: {
            prompt: "Araştırmayı analiz et",
            sourceContext: "Araştırma: {{steps.s1.output}}",
          },
          dependsOn: [],
          description: "Analiz et",
        },
        {
          id: "s3",
          capability: "document_write",
          args: { content: "Analiz: {{steps.s2.output}}" },
          dependsOn: [],
          description: "Rapor yaz",
        },
      ],
    },
    ["web_research", "text_analyze", "document_write"],
  );

  assert.deepEqual(steps?.[1]?.dependsOn, ["s1"]);
  assert.deepEqual(steps?.[2]?.dependsOn, ["s2"]);
});

test("a single-step plan is materialized, not discarded", () => {
  // Canlı arıza: "Masaüstünde ne var" tek yetenek (directory_tree) gerektiriyor.
  // Eskiden hem prompt hem kod ">=2 adım" dayattığı için plan BOŞ gidiyordu;
  // masaüstü hiçbir şey yürütmüyor, plan etiketini cevap sanıp yansıtıyordu.
  const steps = normalizeMaterializedSteps({
    steps: [{ id: "s1", capability: "directory_tree", args: { path: "~/Desktop" } }],
  });
  assert.ok(steps, "tek adımlı plan atıldı");
  assert.equal(steps?.length, 1);
  assert.equal(steps?.[0]?.capability, "directory_tree");
});

test("planning prompt no longer demands two steps", () => {
  const prompt = buildPlanningPrompt(workOrder("Masaüstünde ne var"), [
    "directory_tree",
  ]);
  assert.ok(!prompt.includes(">=2 steps"), "iki adım dayatması geri gelmiş");
  assert.ok(prompt.includes("single-step plan is valid"));
  assert.match(prompt, /args.*JSON-encoded object/);
});

test("materialized plan schema binds capability names and transports open args safely", () => {
  const schema = buildMaterializedPlanResponseSchema([
    "directory_tree",
    "document_read",
    "directory_tree",
    "INVALID CAPABILITY",
  ]) as {
    additionalProperties: boolean;
    properties: {
      steps: {
        items: {
          additionalProperties: boolean;
          properties: {
            capability: { enum: string[] };
            args: { type: string };
          };
        };
      };
    };
  };

  assert.equal(schema.additionalProperties, false);
  assert.equal(schema.properties.steps.items.additionalProperties, false);
  assert.deepEqual(
    schema.properties.steps.items.properties.capability.enum,
    ["directory_tree", "document_read"],
  );
  assert.equal(schema.properties.steps.items.properties.args.type, "string");
});

test("normalizer decodes strict-schema argument JSON before desktop dispatch", () => {
  const steps = normalizeMaterializedSteps(
    {
      steps: [
        {
          id: "s1",
          capability: "directory_tree",
          args: JSON.stringify({ path: "~/Desktop", maxDepth: 2 }),
          dependsOn: [],
          description: "Masaüstü ağacını çıkar",
        },
      ],
    },
    ["directory_tree"],
  );

  assert.deepEqual(steps?.[0]?.args, { path: "~/Desktop", maxDepth: 2 });
  assert.equal(
    normalizeMaterializedSteps(
      {
        steps: [
          {
            id: "s1",
            capability: "directory_tree",
            args: "not-json",
          },
        ],
      },
      ["directory_tree"],
    ),
    null,
  );
});

test("normalizer recovers nested and fenced JSON-encoded arguments", () => {
  const encodedArgs = {
    title: "Yaşam Öyküsü",
    prompt: "İki sayfalık belge hazırla",
    outputPath: "~/Desktop/Yasam-Oykusu.docx",
  };
  const nested = normalizeMaterializedSteps(
    {
      steps: [
        {
          id: "s1",
          capability: "document_write",
          args: JSON.stringify(JSON.stringify(encodedArgs)),
          dependsOn: [],
          description: "Belgeyi yaz",
        },
      ],
    },
    ["document_write"],
  );
  const fenced = normalizeMaterializedSteps(
    {
      steps: [
        {
          id: "s1",
          capability: "document_write",
          args: `\`\`\`json\n${JSON.stringify(encodedArgs)}\n\`\`\``,
          dependsOn: [],
          description: "Belgeyi yaz",
        },
      ],
    },
    ["document_write"],
  );

  assert.equal(nested?.[0]?.args.outputPath, "~/Desktop/Yasam-Oykusu.docx");
  assert.equal(fenced?.[0]?.args.outputPath, "~/Desktop/Yasam-Oykusu.docx");
});

test("semantic compiler fallback accepts only authorized reversible plans", () => {
  const order = workOrder("İki sayfalık yaşam öyküsünü masaüstüne kaydet", [
    "document_write",
  ]);
  order.workType = "data_workflow";
  order.semanticGoal = {
    contract: "elyan.semantic_task_contract.v1",
    objective: "İki sayfalık yaşam öyküsü belgesi üret",
    constraints: [],
    successCriteria: ["Belge artifact kanıtıyla teslim edilir."],
    requiredCapabilities: ["document_write"],
    forbiddenCapabilities: [],
    ambiguityPolicy: "safe_assumption",
    risk: {
      localPrivate: false,
      sideEffect: true,
      irreversible: false,
    },
  };
  order.planPreview.steps = [
    {
      id: "write",
      capability: "document_write",
      args: {
        title: "Yaşam Öyküsü",
        prompt: "İki sayfalık yaşam öyküsü hazırla",
        outputPath: "~/Desktop/Yasam-Oykusu.docx",
      },
      dependsOn: [],
      description: "Belgeyi yaz",
    },
  ];

  assert.equal(
    compileValidatedSemanticFallback(order, ["document_write"])?.length,
    1,
  );
  order.semanticGoal.forbiddenCapabilities = ["document_write"];
  assert.equal(compileValidatedSemanticFallback(order, []), null);
  order.semanticGoal.forbiddenCapabilities = [];
  order.autonomy = {
    mode: "night_watch",
    unattended: true,
    jobId: "night-1",
    allowedCapabilities: ["text_analyze"],
    evidence: {
      source: "night_watch",
      ref: "job-1",
      note: "read only",
    },
  };
  assert.equal(compileValidatedSemanticFallback(order, []), null);
});

test("work-order resource scope rejects model-selected paths outside authorized roots", () => {
  const order = workOrder("İki sayfalık yaşam öyküsünü masaüstüne kaydet", [
    "document_write",
  ]);
  order.semanticGoal = {
    contract: "elyan.semantic_task_contract.v1",
    objective: "İki sayfalık yaşam öyküsü belgesi üret",
    constraints: [],
    successCriteria: ["Belge artifact kanıtıyla teslim edilir."],
    requiredCapabilities: ["document_write"],
    forbiddenCapabilities: [],
    ambiguityPolicy: "safe_assumption",
    risk: {
      localPrivate: false,
      sideEffect: true,
      irreversible: false,
    },
  };
  order.resourceScope = {
    contract: "elyan.resource_scope.v1",
    readRoots: ["workspace"],
    writeRoots: ["~/Desktop"],
  };
  order.planPreview.steps = [
    {
      id: "write",
      capability: "document_write",
      args: {
        title: "Yaşam Öyküsü",
        prompt: "İki sayfalık yaşam öyküsü hazırla",
        outputPath: "~/Desktop/yasam-oykusu.docx",
      },
      dependsOn: [],
      description: "Belgeyi yaz",
    },
  ];

  assert.deepEqual(
    validateMaterializedPlanAgainstWorkOrder(order.planPreview.steps, order),
    [],
  );
  const outsideScope = structuredClone(order.planPreview.steps);
  outsideScope[0]!.args.outputPath = "/tmp/yasam-oykusu.docx";
  assert.match(
    validateMaterializedPlanAgainstWorkOrder(outsideScope, order).join("\n"),
    /outside the authorized WorkOrder resource scope/u,
  );
  const traversal = structuredClone(order.planPreview.steps);
  traversal[0]!.args.outputPath =
    "~/Desktop/../.ssh/authorized_keys";
  assert.match(
    validateMaterializedPlanAgainstWorkOrder(traversal, order).join("\n"),
    /outside the authorized WorkOrder resource scope/u,
  );
  const selectedPaths = structuredClone(order.planPreview.steps);
  selectedPaths[0]!.args.selectedPaths = [
    "~/Desktop/yasam-oykusu.docx",
    "/etc/passwd",
  ];
  assert.match(
    validateMaterializedPlanAgainstWorkOrder(selectedPaths, order).join("\n"),
    /outside the authorized WorkOrder resource scope/u,
  );
});

test("plan contract validation rejects missing required args and ungrounded paths", () => {
  assert.deepEqual(
    validateMaterializedPlanContracts([
      {
        id: "s1",
        capability: "directory_tree",
        args: { path: "." },
        dependsOn: [],
        description: "Listele",
      },
      {
        id: "s2",
        capability: "file_read",
        args: { path: "notlar.txt" },
        dependsOn: ["s1"],
        description: "Oku",
      },
      {
        id: "s3",
        capability: "text_analyze",
        args: { text: "{{steps.s2.output}}" },
        dependsOn: ["s2"],
        description: "Özetle",
      },
    ]),
    [
      "s1: args.path must use an explicit root such as ~/Desktop, workspace/, an absolute path, or a prior-step reference",
      "s2: args.path must use an explicit root such as ~/Desktop, workspace/, an absolute path, or a prior-step reference",
      "s3: text_analyze requires args.prompt",
    ],
  );

  assert.deepEqual(
    validateMaterializedPlanContracts([
      {
        id: "s1",
        capability: "file_read",
        args: { path: "~/Desktop/notlar.txt" },
        dependsOn: [],
        description: "Oku",
      },
      {
        id: "s2",
        capability: "text_analyze",
        args: {
          prompt: "Kısa özet çıkar",
          sourceContext: "{{steps.s1.output}}",
        },
        dependsOn: ["s1"],
        description: "Özetle",
      },
    ]),
    [],
  );

});

test("work-order validation rejects partial plans, cycles, and private-to-web flow", () => {
  const order = workOrder("Araştır ve belge üret", [
    "web_research",
    "document_write",
  ]);
  order.semanticGoal = {
    contract: "elyan.semantic_task_contract.v1",
    objective: "Kaynaklı belge üret",
    constraints: [],
    successCriteria: ["Belge artifact olarak teslim edilir."],
    requiredCapabilities: ["web_research", "document_write"],
    forbiddenCapabilities: [],
    ambiguityPolicy: "safe_assumption",
    risk: {
      localPrivate: false,
      sideEffect: true,
      irreversible: false,
    },
  };
  order.planPreview.steps = [
    {
      id: "research",
      capability: "web_research",
      args: { query: "public tarih kaynakları" },
      dependsOn: [],
      description: "Araştır",
    },
    {
      id: "write",
      capability: "document_write",
      args: { prompt: "{{steps.research.output}}" },
      dependsOn: ["research"],
      description: "Yaz",
    },
  ];

  const partialIssues = validateMaterializedPlanAgainstWorkOrder(
    [order.planPreview.steps[0]!],
    order,
  );
  assert.match(
    partialIssues.join("\n"),
    /semantic work order requires capability document_write/,
  );
  assert.match(partialIssues.join("\n"), /artifact-producing capability/);

  const cycleIssues = validateMaterializedPlanContracts([
    {
      id: "s1",
      capability: "web_research",
      args: { query: "public kaynak" },
      dependsOn: ["s2"],
      description: "Araştır",
    },
    {
      id: "s2",
      capability: "document_write",
      args: { prompt: "{{steps.s1.output}}" },
      dependsOn: ["s1"],
      description: "Yaz",
    },
  ]);
  assert.match(cycleIssues.join("\n"), /dependsOn must reference an earlier step/);

  const privateWebIssues = validateMaterializedPlanAgainstWorkOrder(
    [
      {
        id: "read",
        capability: "document_read",
        args: { path: "~/Desktop/private.docx" },
        dependsOn: [],
        description: "Oku",
      },
      {
        id: "research",
        capability: "web_research",
        args: { query: "{{steps.read.output}}" },
        dependsOn: ["read"],
        description: "Araştır",
      },
    ],
    {
      ...order,
      requiredCapabilities: ["document_read", "web_research"],
      planPreview: {
        ...order.planPreview,
        steps: [
          {
            id: "read",
            capability: "document_read",
            args: { path: "~/Desktop/private.docx" },
            description: "Oku",
          },
          {
            id: "research",
            capability: "web_research",
            args: { query: "public kaynak" },
            description: "Araştır",
          },
        ],
      },
      expectedOutputs: [{ kind: "chat_result", format: "elyan_blocks.v2", required: true }],
    },
  );
  assert.match(privateWebIssues.join("\n"), /cannot consume prior-step/);
  assert.match(privateWebIssues.join("\n"), /cannot depend on local-private/);

  const literalPrivateQueryIssues = validateMaterializedPlanAgainstWorkOrder(
    [
      {
        id: "research",
        capability: "web_research",
        args: { query: "Ayşe Demir bipolar tanısı ilaçları" },
        dependsOn: [],
        description: "Araştır",
      },
      order.planPreview.steps[1]!,
    ],
    {
      ...order,
      semanticGoal: {
        ...order.semanticGoal,
        risk: {
          ...order.semanticGoal.risk,
          localPrivate: true,
        },
      },
    },
  );
  assert.match(
    literalPrivateQueryIssues.join("\n"),
    /contains unapproved private task material/u,
  );
});

test("planning prompt stays below the backend request budget with the full catalog", () => {
  clearPlanningCatalogCacheForTests();
  const prompt = buildPlanningPrompt(
    workOrder("Karmaşık bir masaüstü görevi için doğrulanabilir plan hazırla"),
    DESKTOP_CAPABILITY_MANIFEST.map((entry) => entry.name),
  );

  assert.ok(Buffer.byteLength(prompt, "utf8") <= MATERIALIZE_PROMPT_MAX_BYTES);
  assert.match(prompt, /TOOL CAPABILITY CATALOG/);
  assert.match(prompt, /Output EXACTLY ONE valid json object/);
  clearPlanningCatalogCacheForTests();
});

test("planning prompt reuses compiled catalog sections without caching user text", () => {
  clearPlanningCatalogCacheForTests();
  const allowed = ["document_write", "text_analyze", "web_research"];
  const first = buildPlanningPrompt(
    workOrder("Gizli müşteri planını Word raporu yap", allowed),
    allowed,
  );
  const second = buildPlanningPrompt(
    workOrder("Başka bir hedef için aynı araç kapsamını kullan", allowed),
    allowed,
  );
  const stats = getPlanningCatalogCacheStats();
  const serializedStats = JSON.stringify(stats);

  assert.notEqual(first, second);
  assert.equal(stats.entries, 1);
  assert.equal(stats.hits, 1);
  assert.doesNotMatch(serializedStats, /Gizli müşteri/u);
  assert.doesNotMatch(serializedStats, /Başka bir hedef/u);
  clearPlanningCatalogCacheForTests();
});

test("a plan with no usable capability still returns nothing", () => {
  assert.equal(normalizeMaterializedSteps({ steps: [] }), null);
  assert.equal(
    normalizeMaterializedSteps({ steps: [{ capability: "uydurma_yetenek" }] }),
    null,
  );
});

test("desktop preparation marker persists safe readiness after planning settles", async () => {
  let writtenPayload: unknown = null;
  let storedPayload: unknown = null;
  const deletedBlobIds: string[] = [];
  const task = {
    id: "task-prepare-1",
    userId: "user-1",
    payloadBlobId: "blob-old",
    payload: {
      desktopWorkOrder: {
        planPreview: {
          planSource: "heuristic",
          planPreparation: { status: "pending" },
          steps: [{ id: "stale", capability: "desktop_operator.run", args: {} }],
        },
      },
    },
  };
  const latestTask = {
    ...task,
    payload: {
      desktopWorkOrder: {
        planPreview: {
          planSource: "server_materialized",
          planPreparation: { status: "pending" },
          steps: [{ id: "s1", capability: "directory_tree", args: {} }],
        },
      },
    },
  };
  const app = {
    db: {
      select() {
        return {
          from() {
            return {
              where() {
                return { limit: async () => [latestTask] };
              },
            };
          },
        };
      },
      update() {
        return {
          set(values: { payload: unknown; payloadBlobId?: string }) {
            writtenPayload = values.payload;
            assert.equal(values.payloadBlobId, "blob-new");
            return { where: async () => undefined };
          },
        };
      },
    },
    services: {
      blobs: {
        async storeJson(input: { value: unknown }) {
          storedPayload = input.value;
          return { blobId: "blob-new" };
        },
        async deleteOwnedReference(input: { blobId: string }) {
          deletedBlobIds.push(input.blobId);
          return true;
        },
      },
    },
  };

  // A retry may observe an already-persisted server plan even when this worker
  // did not perform the original model call.
  await markDesktopPlanPrepared(app as never, task as never, false);

  const payload = writtenPayload as {
    desktopWorkOrder: {
      planPreview: {
        planSource: string;
        planPreparation: {
          status: string;
          outcome: string;
          preparedAt?: string;
        };
      };
    };
  };
  assert.deepEqual(
    payload.desktopWorkOrder.planPreview.planPreparation,
    {
      status: "ready",
      outcome: "materialized",
      preparedAt:
        payload.desktopWorkOrder.planPreview.planPreparation.preparedAt,
    },
  );
  assert.match(
    payload.desktopWorkOrder.planPreview.planPreparation.preparedAt ?? "",
    /^\d{4}-\d{2}-\d{2}T/,
  );
  assert.equal(
    payload.desktopWorkOrder.planPreview.planSource,
    "server_materialized",
  );
  assert.deepEqual(storedPayload, writtenPayload);
  assert.equal(task.payload, writtenPayload);
  assert.equal(task.payloadBlobId, "blob-new");
  assert.deepEqual(deletedBlobIds, ["blob-old"]);
});

test("desktop preparation marker fails closed when no model plan is available", async () => {
  let writtenPayload: unknown = null;
  const task = {
    id: "task-prepare-failed",
    userId: "user-1",
    payloadBlobId: null,
    payload: {
      desktopWorkOrder: {
        planPreview: {
          planSource: "heuristic",
          planPreparation: { status: "pending" },
          steps: [
            { id: "unsafe", capability: "desktop_operator.run", args: {} },
          ],
        },
      },
    },
  };
  const app = {
    db: {
      select() {
        return {
          from() {
            return {
              where() {
                return { limit: async () => [task] };
              },
            };
          },
        };
      },
      update() {
        return {
          set(values: { payload: unknown }) {
            writtenPayload = values.payload;
            return { where: async () => undefined };
          },
        };
      },
    },
    services: {
      blobs: {
        async storeJson() {
          return null;
        },
      },
    },
  };

  await markDesktopPlanPrepared(app as never, task as never, false);

  const preparation = (
    writtenPayload as {
      desktopWorkOrder: {
        planPreview: { planPreparation: Record<string, unknown> };
      };
    }
  ).desktopWorkOrder.planPreview.planPreparation;
  assert.equal(preparation.status, "failed");
  assert.equal(preparation.outcome, "model_plan_unavailable");
});

test("plan contract validation rejects invented enum values and names the valid ones", () => {
  // Canlı arıza: planlayıcı browser_control için olmayan bir eylem uydurdu ve
  // iş "Geçersiz tarayıcı eylemi." ile öldü. Geçerli değerler yalnız argüman
  // açıklamasının düzyazısındaydı; hiçbir katman kontrol edemiyordu.
  const issues = validateMaterializedPlanContracts([
    {
      id: "s1",
      capability: "browser_control",
      args: { action: "close_tab" },
      dependsOn: [],
      description: "Sekmeyi kapat",
    },
  ]);
  assert.equal(issues.length, 1);
  assert.match(issues[0], /args\.action="close_tab" is not a valid value/u);
  // Hata metni geçerli listeyi TAŞIMALI: replan ancak bunu okuyarak kendini
  // düzeltebilir. Reddetmek tek başına modele hiçbir şey öğretmez.
  for (const allowed of ["open_url", "search", "play_youtube", "new_tab"]) {
    assert.ok(
      issues[0].includes(allowed),
      `geçerli değer hata metninde yok: ${allowed}`,
    );
  }
});

test("plan contract validation accepts declared enum values case-insensitively", () => {
  assert.deepEqual(
    validateMaterializedPlanContracts([
      {
        id: "s1",
        capability: "browser_control",
        args: { action: "new_tab" },
        dependsOn: [],
        description: "Yeni sekme",
      },
      {
        id: "s2",
        capability: "math_solve",
        args: { expression: "12000+8500", mode: "Evaluate" },
        dependsOn: [],
        description: "Hesapla",
      },
    ]),
    [],
  );
});
