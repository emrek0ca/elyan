import assert from "node:assert/strict";
import test from "node:test";
import {
  extractStepOutcomes,
  scoreStepOutcome,
} from "./step-outcome-ledger.js";

// ---------------------------------------------------------------------------
// "Hangi aracı ne zaman kullanmalı" sorusunun cevabı GÖREVDE değil ADIMDA.
//
// Ölçüldü (2026-08-22): agent_steps 0 satır, operator_steps 0 satır,
// learning_events 45.676 satır ama araç düzeyi sonuç YOK. Yani araç seçimini
// öğrenebilecek tek veri kaynağı hiç doldurulmamış.
// ---------------------------------------------------------------------------

const LIVE_RESULT = {
  toolEvents: [
    {
      ok: true,
      tool: "document_write",
      output: "DOCX oluşturuldu: x.docx",
      verified: true,
      errorCode: "",
    },
  ],
};

test("araç olayları sonuçtan çıkarılır", () => {
  const steps = extractStepOutcomes(LIVE_RESULT);
  assert.equal(steps.length, 1);
  assert.equal(steps[0].tool, "document_write");
  assert.equal(steps[0].ok, true);
  assert.equal(steps[0].verified, true);
});

test("araç adı yoksa kayıt üretilmez", () => {
  assert.deepEqual(extractStepOutcomes({ toolEvents: [{ ok: true }] }), []);
  assert.deepEqual(extractStepOutcomes(null), []);
});

test("GÖREV başarısızsa araç 'ok' dese bile skor sıfır", () => {
  // document_write dosyayı yazdı ama içine konu tarifi yazıldıysa o çağrı
  // başarılı SAYILMAZ. Bu ayrım olmadan model yanlış şeyi öğrenir.
  const score = scoreStepOutcome({
    step: { tool: "document_write", ok: true, verified: true },
    taskVerdict: "unfulfilled",
  });
  assert.equal(score, 0);
});

test("bozuk sonuçta skor kısmi", () => {
  assert.equal(
    scoreStepOutcome({
      step: { tool: "document_write", ok: true, verified: true },
      taskVerdict: "degraded",
    }),
    50,
  );
});

test("tam sonuçta skor tam", () => {
  assert.equal(
    scoreStepOutcome({
      step: { tool: "document_write", ok: true, verified: true },
      taskVerdict: "fulfilled",
    }),
    100,
  );
});

test("doğrulanmamış araç tam puan almaz", () => {
  assert.equal(
    scoreStepOutcome({
      step: { tool: "shell_run", ok: true, verified: false },
      taskVerdict: "fulfilled",
    }),
    75,
  );
});

test("araç hata verdiyse skor sıfır", () => {
  assert.equal(
    scoreStepOutcome({
      step: { tool: "open_app", ok: false, errorCode: "NOT_FOUND" },
      taskVerdict: "fulfilled",
    }),
    0,
  );
});
