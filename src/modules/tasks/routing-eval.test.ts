import test from "node:test";
import assert from "node:assert/strict";
import { runRoutingEval } from "./routing-eval.js";
import {
  ROUTING_EVAL_CORPUS,
  ROUTING_EVAL_HELDOUT,
} from "./routing-eval-corpus.js";
import { getDesktopCapabilityOntology } from "./desktop-capability-ontology.js";

// Yönlendirme kalitesinin REGRESYON KAPISI.
//
// Eşikler keyfi değil, ölçülen mevcut seviyenin biraz altına konuldu: amaç
// bugünkü skoru dondurmak değil, DÜŞMESİNİ yakalamak. Bir prose yaması ya da
// yeni bir yetenek kaliteyi bozarsa burası kırmızı yanar.
//
// Bu test yalnız sözcüksel katmanı ölçer (hermetik, model gerektirmez).
// Gerçek anlamsal katman (e5) semantic compute worker'a bağlı olduğu için
// birim testinde koşturulmaz; onun ölçümü scripts üzerinden yapılır.

test("routing quality does not regress on the phrasebook-aligned corpus", () => {
  const report = runRoutingEval(ROUTING_EVAL_CORPUS);
  assert.ok(
    report.top1Rate >= 0.92,
    `top-1 ${report.top1Rate} < 0.92 — yönlendirme geriledi`,
  );
  assert.ok(
    report.criticalViolations <= 2,
    `kritik ihlal ${report.criticalViolations} > 2 — yanlış yetenek ilk sırada`,
  );
});

test("routing quality does not regress on the held-out corpus", () => {
  // Tutulan küme sözlükle ifade paylaşmaz; buradaki skor GENELLEMEYİ ölçer.
  // Sözcüksel katman tek başına düşük kalır — beklenen budur, eşik ona göre.
  const report = runRoutingEval(ROUTING_EVAL_HELDOUT);
  assert.ok(
    report.top1Rate >= 0.4,
    `tutulan küme top-1 ${report.top1Rate} < 0.40 — genelleme geriledi`,
  );
});

test("held-out corpus stays independent from the capability phrasebook", () => {
  // Tutulan küme ölçüm aletidir. İfadeleri sözlüğe kopyalanırsa ezberi
  // ölçmeye başlar ve genelleme rakamı yalan söyler.
  const phrasebook = new Set<string>();
  for (const entry of getDesktopCapabilityOntology()) {
    for (const utterance of entry.manifest.utterances) {
      phrasebook.add(utterance.trim().toLocaleLowerCase("tr-TR"));
    }
  }
  for (const testCase of ROUTING_EVAL_HELDOUT) {
    assert.ok(
      !phrasebook.has(testCase.utterance.trim().toLocaleLowerCase("tr-TR")),
      `tutulan küme ifadesi sözlüğe sızmış: "${testCase.utterance}"`,
    );
  }
});
