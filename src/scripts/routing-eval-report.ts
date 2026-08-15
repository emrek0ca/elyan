import {
  formatRoutingEvalReport,
  runRoutingEval,
  type RoutingEvalReport,
} from "../modules/tasks/routing-eval.js";
import {
  ROUTING_EVAL_CORPUS,
  ROUTING_EVAL_HELDOUT,
} from "../modules/tasks/routing-eval-corpus.js";
import { matchDesktopCapabilitiesWithEmbeddings } from "../modules/tasks/desktop-capability-embedding-match.js";

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

/**
 * İKİ AŞAMA AYRI ÖLÇÜLÜR.
 *
 * Üretim yolu `matchDesktopCapabilitiesWithEmbeddings`: önce sözcüksel katman
 * 128 aday üretir, sonra e5 yeniden sıralar. Yalnız sözcüksel katmanı ölçmek
 * yanıltıcıdır — ama e5 aşamasını ölçmemek de öyle, çünkü e5 erişilemezse
 * (model yüklenmemiş, timeout) üretim SESSİZCE sözcüksel skora düşer. İki
 * sayıyı yan yana görmek, o düşüşün bedelini görünür kılar.
 */
async function runFullPipelineEval(corpus: typeof ROUTING_EVAL_CORPUS) {
  let top1 = 0;
  let scored = 0;
  const misses: string[] = [];
  for (const testCase of corpus) {
    if (!testCase.expected) continue;
    scored += 1;
    const matches = await matchDesktopCapabilitiesWithEmbeddings({
      query: testCase.utterance,
      intent: testCase.intent ?? null,
      sideEffectLevel: testCase.sideEffectLevel ?? null,
      limit: 3,
    });
    const acceptable = new Set([testCase.expected, ...(testCase.alsoAcceptable ?? [])]);
    if (matches[0] && acceptable.has(matches[0].capability)) {
      top1 += 1;
    } else {
      misses.push(
        `  "${testCase.utterance}" → bekleniyordu ${testCase.expected}, geldi ${matches.map((m) => m.capability).join(", ") || "(yok)"}`,
      );
    }
  }
  return { scored, top1, rate: scored > 0 ? top1 / scored : 0, misses };
}

const asJson = process.argv.includes("--json");
const withEmbeddings = process.argv.includes("--full");
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

if (withEmbeddings) {
  console.log("\n===== TAM BORU HATTI (sözcüksel + e5 yeniden sıralama) =====");
  for (const [name, corpus] of [
    ["KORPUS", ROUTING_EVAL_CORPUS],
    ["TUTULAN", ROUTING_EVAL_HELDOUT],
  ] as const) {
    const full = await runFullPipelineEval(corpus);
    console.log(`${name}: top-1 ${full.top1}/${full.scored} (${(full.rate * 100).toFixed(1)}%)`);
    for (const miss of full.misses.slice(0, 12)) console.log(miss);
  }
}
