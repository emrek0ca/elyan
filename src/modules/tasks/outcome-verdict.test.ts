import assert from "node:assert/strict";
import test from "node:test";
import {
  assessTaskOutcome,
  filenameEchoesRequest,
  looksLikeClarification,
} from "./outcome-verdict.js";

// ---------------------------------------------------------------------------
// "TAMAMLANDI" İLE "İSTEDİĞİM OLDU" AYNI ŞEY DEĞİL.
//
// Epizodik hafıza kurulduğunda ölçüm şunu gösterdi: aynı cümle hem
// `server_brain → completed` hem `desktop_runtime → completed` olarak kayıtlı.
// Oysa server_brain turları çöp PDF üreten ve netleştirme sorusu soran
// turlardı. Bu etiketle öğrenmek yanlış dersi kalıcılaştırır.
// ---------------------------------------------------------------------------

const REQUEST = "masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet";
const ARTIFACT_REQUIRED = [{ kind: "artifact", required: true }];

test("netleştirme sorusu başarı sayılmaz", () => {
  const result = assessTaskOutcome({
    status: "completed",
    request: REQUEST,
    expectedOutputs: ARTIFACT_REQUIRED,
    result: { blocks: [{ type: "artifact", artifactName: "x.pdf" }] },
    assistantText: "Netleştireyim: tam olarak neyi yapmamı istiyorsun?",
  });
  assert.equal(result.verdict, "unfulfilled");
  assert.ok(result.reasons.includes("answer_is_clarification"));
});

test("zorunlu artefakt yoksa iş yapılmamıştır", () => {
  const result = assessTaskOutcome({
    status: "completed",
    request: REQUEST,
    expectedOutputs: ARTIFACT_REQUIRED,
    result: { blocks: [{ type: "text", markdown: "hazır" }] },
  });
  assert.equal(result.verdict, "unfulfilled");
  assert.ok(result.reasons.includes("required_artifact_missing"));
});

test("pdf istenip docx üretilmesi BOZUK sonuçtur", () => {
  // Canlı çıktı (b2845b50): kullanıcı PDF istedi, .docx geldi.
  const result = assessTaskOutcome({
    status: "completed",
    request: REQUEST,
    expectedOutputs: ARTIFACT_REQUIRED,
    result: { blocks: [{ type: "artifact", artifactName: "Zurafa-Raporu.docx" }] },
  });
  assert.equal(result.verdict, "degraded");
  assert.ok(result.reasons.some((reason) => reason.startsWith("format_mismatch")));
});

test("dosya adı isteğin ekosuysa bozuk sonuçtur", () => {
  const result = assessTaskOutcome({
    status: "completed",
    request: REQUEST,
    expectedOutputs: ARTIFACT_REQUIRED,
    result: {
      blocks: [
        {
          type: "artifact",
          artifactName: "masaustune-zurafalar-hakkinda-bir-pdf-hazirla-ve-kaydet.pdf",
        },
      ],
    },
  });
  assert.equal(result.verdict, "degraded");
  assert.ok(result.reasons.includes("filename_echoes_request"));
});

test("doğru sonuç TAM sayılır", () => {
  const result = assessTaskOutcome({
    status: "completed",
    request: REQUEST,
    expectedOutputs: ARTIFACT_REQUIRED,
    result: { blocks: [{ type: "artifact", artifactName: "Zurafa-Bilimsel-Raporu.pdf" }] },
    assistantText: "PDF masaüstüne kaydedildi.",
  });
  assert.equal(result.verdict, "fulfilled");
  assert.deepEqual(result.reasons, []);
});

test("terminal olmayan/başarısız durum yerine getirilmemiştir", () => {
  assert.equal(
    assessTaskOutcome({ status: "failed", request: REQUEST, error: "plan yok" }).verdict,
    "unfulfilled",
  );
});

test("yardımcılar tek tek doğru", () => {
  assert.equal(looksLikeClarification("Bunu nasıl yapayım?"), true);
  assert.equal(looksLikeClarification("Rapor masaüstüne kaydedildi."), false);
  assert.equal(
    filenameEchoesRequest("masaustune-zurafalar-hakkinda-bir-rapor-hazirla.docx", REQUEST),
    true,
  );
  assert.equal(filenameEchoesRequest("Zurafa-Raporu.docx", REQUEST), false);
});
