import test from "node:test";
import assert from "node:assert/strict";
import {
  buildPlanningPrompt,
  renderPlanningFewShots,
} from "./materialize-plan.js";
import type { DesktopWorkOrder } from "./desktop-work-order.js";

function workOrder(summary: string): DesktopWorkOrder {
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
    requiredCapabilities: ["math_solve", "web_research", "document_write", "spreadsheet_write", "presentation_write"],
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
    ["math_solve", "web_research", "document_write", "spreadsheet_write", "presentation_write"],
  );

  assert.match(prompt, /Accounting calculation \+ research \+ report/);
  assert.match(prompt, /"expression":"\(12000\+8500\)\*0\.20"/);
  assert.match(prompt, /"query":"hizmet faturasi KDV yuzde 20 kurallari Turkiye"/);
  assert.match(prompt, /"content":"KDV hesabi: \{\{steps\.s1\.output\}\}\\n\\nArastirma: \{\{steps\.s2\.output\}\}"/);
  assert.match(prompt, /tax amount.*\(12000\+8500\)\*0\.20/i);
  assert.match(prompt, /tax-included total.*\(12000\+8500\)\*1\.20/i);
});

test("desktop materialization prompt keeps research queries public and writer args contextual", () => {
  const fewShots = renderPlanningFewShots();

  assert.match(fewShots, /Legal research \+ defense draft/);
  assert.match(fewShots, /kira uyusmazligi tahliye davasi savunma dilekcesi mevzuat emsal/);
  assert.match(fewShots, /Student research \+ presentation/);
  assert.match(fewShots, /quantum annealing vs classical optimization explanation examples/);

  const prompt = buildPlanningPrompt(
    workOrder("Avukat gibi çalış. Dosya özeti özel kalsın; kira uyuşmazlığını araştır ve savunma dilekçesi hazırla."),
    ["web_research", "document_write"],
  );

  assert.match(prompt, /Do not pass the full user goal, private case facts, file summaries, or writing instructions as the query/);
  assert.match(prompt, /preserve private case\/test\/project facts in writer args/);
});
