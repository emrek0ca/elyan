import {
  formatRoutingEvalReport,
  runRoutingEval,
  type RoutingEvalReport,
} from "../modules/tasks/routing-eval.js";
import {
  ROUTING_EVAL_CORPUS,
  ROUTING_EVAL_HELDOUT,
} from "../modules/tasks/routing-eval-corpus.js";

/**
 * YÖNLENDİRME ÖLÇÜM KAPISI.
 *
 * Kural: yönlendirmeye/kelime listelerine/niyet kapılarına dokunan hiçbir
 * değişiklik, bu raporda delta göstermeden çıkmaz. Bu projede "tahmin sert
 * sözleşmeye dönüşüyor" hata sınıfı defalarca tekrarlandı; kapı o yüzden var.
 *
 *   npm run eval:routing            → rapor
 *   npm run eval:routing -- --json  → makine okunur (CI/karşılaştırma)
 *
 * TUTULAN kümeye BAKIP AYAR YAPMA. Korpus ile tutulan küme arasındaki fark
 * gerçek genelleme payıdır; tutulana göre ayar yapmak o payı yok eder ve
 * ölçüm anlamsızlaşır.
 */

type Summary = {
  scope: "corpus" | "heldout";
  cases: number;
  top1Ratio: number;
  top3Ratio: number;
  criticalViolations: number;
  overconfident: number;
};

function summarize(scope: Summary["scope"], report: RoutingEvalReport): Summary {
  return {
    scope,
    cases: report.total,
    top1Ratio: Number(report.top1Rate.toFixed(4)),
    top3Ratio: Number(report.top3Rate.toFixed(4)),
    criticalViolations: report.criticalViolations,
    overconfident: report.overconfident,
  };
}

const asJson = process.argv.includes("--json");
const corpusReport = runRoutingEval(ROUTING_EVAL_CORPUS);
const heldoutReport = runRoutingEval(ROUTING_EVAL_HELDOUT);

if (asJson) {
  console.log(
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        corpus: summarize("corpus", corpusReport),
        heldout: summarize("heldout", heldoutReport),
      },
      null,
      2,
    ),
  );
} else {
  console.log(`===== KORPUS (${ROUTING_EVAL_CORPUS.length} vaka) =====`);
  console.log(formatRoutingEvalReport(corpusReport));
  console.log(`\n===== TUTULAN KÜME (${ROUTING_EVAL_HELDOUT.length} vaka) =====`);
  console.log(formatRoutingEvalReport(heldoutReport));
  const corpusTop1 = corpusReport.top1Rate;
  const heldoutTop1 = heldoutReport.top1Rate;
  console.log(
    `\nGENELLEME PAYI: korpus ${(corpusTop1 * 100).toFixed(1)}% → tutulan ${(heldoutTop1 * 100).toFixed(1)}%` +
      ` (fark ${((corpusTop1 - heldoutTop1) * 100).toFixed(1)} puan)`,
  );
}
