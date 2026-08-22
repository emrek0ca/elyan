import assert from "node:assert/strict";
import test from "node:test";
import { normalizeExecutionSteps, toToolResult } from "./execution-step.js";

// ---------------------------------------------------------------------------
// Notion §4 ve §8: capability ile device AYRI kararlardır, ve bir adımın
// çıktısı BAŞKA CİHAZDAKİ adımın girdisi olabilmelidir.
//
// Bugünkü executionPlan yalnız yüzey listesi taşıyor
// (Array<"mobile_local"|"server_brain"|"desktop_runtime">); adım başına cihaz
// yok. "Bilgisayarımdaki faturayı bul ve telefona gönder" bu şekille bölünemez.
// ---------------------------------------------------------------------------

test("cihaz-farkında adımlar sözleşmeye çevrilir", () => {
  const steps = normalizeExecutionSteps([
    { stepId: "s1", device: "desktop", capability: "fuzzy_find" },
    { stepId: "s2", device: "desktop", capability: "document_write", dependsOn: ["s1"] },
    { stepId: "s3", device: "mobile", capability: "present_file", dependsOn: ["s2"] },
  ]);
  assert.equal(steps.length, 3);
  assert.deepEqual(steps.map((s) => s.device), ["desktop", "desktop", "mobile"]);
  assert.deepEqual(steps[2].dependsOn, ["s2"]);
});

test("geçersiz cihaz sessizce uydurulmaz", () => {
  // "Bilmiyorum" ile "control-plane" aynı şey değil.
  const [step] = normalizeExecutionSteps([{ capability: "x", device: "buzdolabi" }]);
  assert.equal(step.device, undefined);
});

test("yeteneksiz adım ATILIR", () => {
  // Yarım adımı "tamamlamak" uydurma üretir.
  assert.deepEqual(normalizeExecutionSteps([{ stepId: "s1", device: "desktop" }]), []);
  assert.deepEqual(normalizeExecutionSteps(null), []);
});

test("sarkan bağımlılık temizlenir", () => {
  const [step] = normalizeExecutionSteps([
    { stepId: "s1", capability: "a", dependsOn: ["olmayan"] },
  ]);
  assert.equal(step.dependsOn, undefined);
});

test("tekrarlanan stepId benzersizleştirilir", () => {
  const steps = normalizeExecutionSteps([
    { stepId: "s1", capability: "a" },
    { stepId: "s1", capability: "b" },
  ]);
  assert.notEqual(steps[0].stepId, steps[1].stepId);
});

test("araç çıktısı standart sözleşmeye çevrilir", () => {
  // Masaüstünün bugünkü toolEvents şekli.
  const result = toToolResult({
    ok: true,
    tool: "document_write",
    output: "DOCX oluşturuldu",
    artifacts: [{ id: "local_abc", kind: "document", location: "desktop", name: "r.docx" }],
    latencyMs: 1200,
  });
  assert.equal(result.success, true);
  assert.equal(result.artifacts?.[0].artifactId, "local_abc");
  assert.equal(result.artifacts?.[0].location, "desktop");
  assert.equal(result.metrics?.latencyMs, 1200);
});

test("hata kodu taşınır ve başarı yanlış olmaz", () => {
  const result = toToolResult({ ok: false, errorCode: "NOT_FOUND" });
  assert.equal(result.success, false);
  assert.equal(result.error?.code, "NOT_FOUND");
});

test("tanınmayan şekil BAŞARISIZ sayılmaz", () => {
  // "Şeklini tanımadım" ile "iş başarısız" ayrı şeylerdir.
  const result = toToolResult("düz metin çıktı");
  assert.equal(result.success, true);
  assert.equal(result.output, "düz metin çıktı");
});
