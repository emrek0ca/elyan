import test from "node:test";
import assert from "node:assert/strict";
import {
  buildPlanningPrompt,
  renderPlanningFewShots,
} from "./materialize-plan.js";
import type { DesktopWorkOrder } from "./desktop-work-order.js";

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
});

test("desktop materialization prompt keeps research queries public and writer args contextual", () => {
  const fewShots = renderPlanningFewShots();

  assert.match(fewShots, /Legal research \+ defense draft/);
  assert.match(fewShots, /kira uyusmazligi tahliye davasi savunma dilekcesi mevzuat emsal/);
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
  assert.match(prompt, /For spreadsheet_write, provide concrete rows\/sheets/);
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
