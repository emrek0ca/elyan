import assert from "node:assert/strict";
import test from "node:test";
import { pruneUnneededResearchSteps } from "./plan-shortest-path.js";
import type { DesktopWorkOrderStep } from "./desktop-work-order.js";

// ---------------------------------------------------------------------------
// Kullanıcının açık isteği: "en hızlı ve en doğru yolu kullanmalıyız";
// modelin zaten bildiği konuda tarayıcı/araştırma yolu en kırılgan yol.
//
// Ölçüm (canlı Groq, gerçek planlama promptu, "zürafalar hakkında rapor"):
//   direktif yokken : 4/4 → web_research → text_analyze → document_write
//   direktif varken : 2/4 tek adım, 2/4 hâlâ text_analyze ekliyor
// Prompt tek başına yetmediği için yapısal budama gerekli.
// ---------------------------------------------------------------------------

function step(
  id: string,
  capability: string,
  args: Record<string, unknown> = {},
  dependsOn: string[] = [],
): DesktopWorkOrderStep {
  return { id, capability, description: "", args, dependsOn } as DesktopWorkOrderStep;
}

test("kalıcı bilgi turunda araştırma ve analiz düşer", () => {
  const result = pruneUnneededResearchSteps({
    steps: [
      step("s1", "web_research", { query: "zürafa" }),
      step("s2", "text_analyze", { prompt: "{{steps.s1.output}}" }, ["s1"]),
      step("s3", "document_write", { prompt: "{{steps.s2.output}}" }, ["s2"]),
    ],
    recency: "stable_knowledge",
  });
  assert.deepEqual(result.steps.map((s) => s.capability), ["document_write"]);
  assert.equal(result.steps[0].args.prompt, "");
  assert.deepEqual(result.steps[0].dependsOn, []);
  assert.deepEqual(result.pruned.sort(), ["s1", "s2"]);
});

test("güncel bilgi turunda araştırma KORUNUR", () => {
  const steps = [
    step("s1", "web_research", { query: "enflasyon" }),
    step("s2", "document_write", { prompt: "{{steps.s1.output}}" }, ["s1"]),
  ];
  const result = pruneUnneededResearchSteps({ steps, recency: "current_facts" });
  assert.equal(result.pruned.length, 0);
  assert.equal(result.steps, steps);
});

test("karar yoksa dokunulmaz", () => {
  const steps = [
    step("s1", "web_research", {}),
    step("s2", "document_write", {}, ["s1"]),
  ];
  assert.equal(pruneUnneededResearchSteps({ steps, recency: null }).pruned.length, 0);
});

test("KULLANICININ KENDİ VERİSİ varsa analiz düşmez", () => {
  // "bu dosyayı özetle ve belge yap" — analiz burada meşrudur.
  const steps = [
    step("s1", "document_read", { path: "~/Desktop/rapor.pdf" }),
    step("s2", "text_analyze", { prompt: "{{steps.s1.output}}" }, ["s1"]),
    step("s3", "document_write", { prompt: "{{steps.s2.output}}" }, ["s2"]),
  ];
  const result = pruneUnneededResearchSteps({ steps, recency: "stable_knowledge" });
  assert.equal(result.pruned.length, 0, "yerel veri okuyan planda budama yapıldı");
});

test("budama sonrası iş yapan adım kalmıyorsa dokunulmaz", () => {
  const steps = [step("s1", "web_research", { query: "x" })];
  assert.equal(
    pruneUnneededResearchSteps({ steps, recency: "stable_knowledge" }).pruned.length,
    0,
  );
});
