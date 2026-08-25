import assert from "node:assert/strict";
import test from "node:test";
import {
  classifyStepFailure,
  evidenceKindsFromValue,
  isLearnableObservation,
  extractStepOutcomes,
  recordStepOutcomes,
  scoreStepOutcome,
  stepEvidenceStrength,
  taskVerificationEvidenceKinds,
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

test("eski masaüstü tool olayı ok alanı olmadan çıktıyı başarı sayar", () => {
  const steps = extractStepOutcomes({
    toolEvents: [{ tool: "close_app", output: "Music kapatıldı" }],
  });
  assert.equal(steps[0]?.ok, true);
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

test("doğrulanmamış araç HİÇ puan almaz", () => {
  // Bu test eskiden 75 bekliyordu: açıkça doğrulanmamış bir çağrı yine de
  // öğrenmeye üç çeyrek kredi yazıyordu. Kanıt kapısı bunu kapattı — kanıtı
  // olmayan çağrı ne başarı ne başarısızlık sayılır; `evidenceBacked=false`
  // ile tahminciye hiç girmez.
  assert.equal(
    scoreStepOutcome({
      step: { tool: "shell_run", ok: true, verified: false },
      taskVerdict: "fulfilled",
    }),
    0,
  );
  // Aynı çağrı kanıt üretmişse kredi geri gelir.
  assert.equal(
    scoreStepOutcome({
      step: {
        tool: "shell_run",
        ok: true,
        verified: false,
        evidenceKinds: ["state_readback"],
      },
      taskVerdict: "fulfilled",
    }),
    100,
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

test("aynı araç retry edildiğinde tek satıra birleşir ve çağrı geçmişi korunur", async () => {
  const inserted: Array<Record<string, unknown>[]> = [];
  const app = {
    db: {
      insert() {
        return {
          values(rows: Record<string, unknown>[]) {
            inserted.push(rows);
            return {
              onConflictDoNothing() {
                return {
                  returning: async () => [{ id: "learning-event-1" }],
                };
              },
            };
          },
        };
      },
    },
    log: { warn() {} },
  } as never;

  const count = await recordStepOutcomes(app, {
    userId: "00000000-0000-4000-8000-000000000201",
    taskId: "00000000-0000-4000-8000-000000000202",
    route: "desktop_runtime",
    device: "desktop",
    intentKind: "close_app",
    assessment: { verdict: "fulfilled", reasons: [] },
    result: {
      toolEvents: [
        { tool: "close_app", ok: false, errorCode: "APP_NOT_FOUND", attempt: 1 },
        { tool: "close_app", ok: true, verified: true, attempt: 2 },
      ],
    },
  });

  assert.equal(count, 1);
  const row = inserted[0]?.[0];
  assert.equal(row?.key, "close_app");
  const metadata = row?.metadata as { callCount?: number; calls?: unknown[] };
  assert.equal(metadata.callCount, 2);
  assert.equal(metadata.calls?.length, 2);
});

test("kanıtsız başarı TAM kredi almaz", () => {
  // Eskiden `verified` alanı olmayan bir başarı 100 alıyordu: "runtime bitti"
  // ile "istenen şey oldu" öğrenmede aynı ağırlıktaydı.
  assert.equal(
    scoreStepOutcome({
      step: { tool: "document_write", ok: true },
      taskVerdict: "fulfilled",
    }),
    0,
  );
});

test("kanıt gücü krediyi belirler", () => {
  const strong = scoreStepOutcome({
    step: { tool: "document_write", ok: true, evidenceKinds: ["artifact"] },
    taskVerdict: "fulfilled",
  });
  const weak = scoreStepOutcome({
    step: { tool: "document_write", ok: true, evidenceKinds: ["runtime_status"] },
    taskVerdict: "fulfilled",
  });
  assert.equal(strong, 100);
  assert.equal(weak, 50);
  assert.equal(
    scoreStepOutcome({
      step: { tool: "document_write", ok: true, evidenceKinds: ["artifact"] },
      taskVerdict: "degraded",
    }),
    50,
  );
});

test("adımın kanıtı yoksa görev düzeyi kanıta düşülür", () => {
  assert.equal(
    stepEvidenceStrength({ tool: "sys_info", ok: true }, ["state_readback"]),
    "strong",
  );
  assert.equal(stepEvidenceStrength({ tool: "sys_info", ok: true }, []), "none");
  assert.equal(
    stepEvidenceStrength({ tool: "sys_info", ok: true, verified: true }, []),
    "strong",
  );
});

test("başarısız veya karşılanmamış çağrı kanıtı ne olursa olsun kredi almaz", () => {
  assert.equal(
    scoreStepOutcome({
      step: { tool: "x", ok: false, evidenceKinds: ["artifact"] },
      taskVerdict: "fulfilled",
    }),
    0,
  );
  assert.equal(
    scoreStepOutcome({
      step: { tool: "x", ok: true, evidenceKinds: ["artifact"] },
      taskVerdict: "unfulfilled",
    }),
    0,
  );
});

test("görev doğrulama kanıtı yalnız GEÇMİŞ kontrollerden okunur", () => {
  assert.deepEqual(
    taskVerificationEvidenceKinds({
      verification: {
        checks: [
          { id: "a", passed: true, evidence: "artifact" },
          { id: "b", passed: false, evidence: "state_readback" },
        ],
      },
    }),
    ["artifact"],
  );
  assert.deepEqual(taskVerificationEvidenceKinds({}), []);
});

test("yürütücünün sözlük kanıtı tür adına indirgenir", () => {
  assert.deepEqual(evidenceKindsFromValue({ path: "/x/y.pdf" }), ["artifact"]);
  assert.deepEqual(evidenceKindsFromValue("state_readback"), ["state_readback"]);
  assert.deepEqual(evidenceKindsFromValue({ note: "ok" }), ["tool_result"]);
  assert.deepEqual(evidenceKindsFromValue(undefined), []);
});

test("onay kapısı araç hatası SAYILMAZ", () => {
  // Onay bekleyen bir araç bozuk değildir. Bunu başarısızlık saymak, onay
  // gerektiren her aracı zamanla "çalışmıyor" ilan etmek olurdu.
  assert.equal(
    classifyStepFailure({ errorCode: "AGENT_LOOP_NEEDS_APPROVAL" }),
    "permission_gate",
  );
  assert.equal(
    isLearnableObservation({
      step: { tool: "file_write", ok: false, errorCode: "AGENT_LOOP_NEEDS_APPROVAL" },
    }),
    false,
  );
});

test("iptal ve plan uyuşmazlığı da araç hakkında kanıt değildir", () => {
  assert.equal(classifyStepFailure({ stopReason: "user_cancel" }), "user_cancel");
  assert.equal(
    classifyStepFailure({ errorCode: "SERVER_PLAN_STEP_MISMATCH" }),
    "plan_mismatch",
  );
  assert.equal(
    isLearnableObservation({
      step: { tool: "x", ok: false, errorCode: "SERVER_PLAN_STEP_MISMATCH" },
    }),
    false,
  );
});

test("gerçek araç hatası öğrenmeye GİRER", () => {
  assert.equal(classifyStepFailure({ errorCode: "APP_NOT_FOUND" }), "tool_failure");
  assert.equal(
    isLearnableObservation({
      step: { tool: "open_app", ok: false, errorCode: "APP_NOT_FOUND" },
    }),
    true,
  );
  // Hata kodu hiç yoksa da araç hatası varsayılır — fail-closed.
  assert.equal(classifyStepFailure({}), "tool_failure");
});
