import {
  formatRoutingEvalReport,
  runRoutingEval,
  type RoutingEvalReport,
} from "../modules/tasks/routing-eval.js";
import {
  ROUTING_EVAL_CORPUS,
  ROUTING_EVAL_HELDOUT,
} from "../modules/tasks/routing-eval-corpus.js";
import {
  isDesktopCapabilityVectorCacheReady,
  matchDesktopCapabilitiesWithEmbeddings,
  warmDesktopCapabilityVectors,
} from "../modules/tasks/desktop-capability-embedding-match.js";
import { resetSemanticComputeWorkerForTests } from "../modules/brain/semantic-compute-client.js";

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
      allowWarmup: false,
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
/**
 * ÜRETİM YOLU ARTIK VARSAYILAN (2026-08-22).
 *
 * Eskiden tam boru hattı yalnız `--full` ile koşuyordu; varsayılan rapor
 * SÖZCÜKSEL katmanı ölçüyordu. Sonuç: haftalardır "genelleme payı 40,6 puan"
 * diye raporladığım sayı, üretimin verdiği kararın DEĞİL bir bileşenin
 * sayısıydı. Aynı anda ölçüldü:
 *
 *   sözcüksel  : korpus 98.1% → tutulan 57.5%  (fark 40.6 puan)
 *   ÜRETİM (e5): korpus 99.0% → tutulan 83.0%  (fark 16.0 puan)
 *
 * Sözcüksel kaçırmaların bir kısmını e5 zaten kurtarıyor (ör. "şu görseli
 * üretiver bana" yalnız sözcüksel katmanda kayıp). Yanlış aşamaya bakmak,
 * iyileştirme çabasını olmayan bir soruna yönlendiriyordu.
 *
 * `--lexical-only` bileşeni tek başına ölçmek için durur; ama artık kapının
 * BAŞLIK sayısı üretim yoludur.
 */
const lexicalOnly = process.argv.includes("--lexical-only");
const corpusReport = runRoutingEval(ROUTING_EVAL_CORPUS);
const heldoutReport = runRoutingEval(ROUTING_EVAL_HELDOUT);

type PipelineResult = Awaited<ReturnType<typeof runFullPipelineEval>>;
let productionCorpus: PipelineResult | null = null;
let productionHeldout: PipelineResult | null = null;
let embeddingsReady = false;
const evalLogger = {
  warn(value: unknown, message?: string) {
    console.error(`[routing-eval] ${message ?? "semantic warning"}`, value);
  },
  info() {},
  debug() {},
};

if (!lexicalOnly) {
  try {
    // The production app warms this asynchronously. The evaluator is the
    // explicit opt-in caller allowed to wait once before scoring the corpus;
    // every measured request below uses the already-ready cache.
    await warmDesktopCapabilityVectors(evalLogger);
    embeddingsReady = isDesktopCapabilityVectorCacheReady();
    if (embeddingsReady) {
      productionCorpus = await runFullPipelineEval(ROUTING_EVAL_CORPUS);
      productionHeldout = await runFullPipelineEval(ROUTING_EVAL_HELDOUT);
    }
  } finally {
    // The semantic worker is unref'd, but its pending scheduler/worker state
    // still kept the old evaluator alive after it had printed its report.
    resetSemanticComputeWorkerForTests();
  }
}

if (asJson) {
  console.log(
    JSON.stringify(
      {
        generatedAt: new Date().toISOString(),
        // Kapının BAŞLIK sayısı: üretim yolu. e5 hazır değilse null —
        // sessizce sözcüksel sayıya düşmek, bu kapıyı yıllarca yanlış
        // aşamaya baktıran hatanın ta kendisiydi.
        production: embeddingsReady
          ? {
              corpus: {
                cases: productionCorpus?.scored ?? 0,
                top1Ratio: Number((productionCorpus?.rate ?? 0).toFixed(4)),
              },
              heldout: {
                cases: productionHeldout?.scored ?? 0,
                top1Ratio: Number((productionHeldout?.rate ?? 0).toFixed(4)),
              },
            }
          : null,
        embeddingsReady,
        lexical: {
          corpus: summarize("corpus", corpusReport),
          heldout: summarize("heldout", heldoutReport),
        },
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
    `\n[BİLEŞEN] sözcüksel katman: korpus ${(corpusTop1 * 100).toFixed(1)}% → tutulan ${(heldoutTop1 * 100).toFixed(1)}%` +
      ` (fark ${((corpusTop1 - heldoutTop1) * 100).toFixed(1)} puan)`,
  );

  if (lexicalOnly) {
    console.log(
      "\n--lexical-only: ÜRETİM yolu ölçülmedi. Yukarıdaki sayı kapının başlık sayısı DEĞİLDİR.",
    );
  } else if (!embeddingsReady || !productionCorpus || !productionHeldout) {
    console.log(
      "\n!!! ÜRETİM YOLU ÖLÇÜLEMEDİ: e5 vektör önbelleği hazır değil." +
        "\n    Üretim bu durumda SESSİZCE sözcüksel skora düşer; kapı da bunu" +
        "\n    sessizce yapmasın diye burada duruyor. Sayıyı geçerli sayma.",
    );
    process.exitCode = 1;
  } else {
    console.log(`\n===== ÜRETİM YOLU (sözcüksel + e5 yeniden sıralama) =====`);
    console.log(
      `KORPUS : top-1 ${productionCorpus.top1}/${productionCorpus.scored} (${(productionCorpus.rate * 100).toFixed(1)}%)`,
    );
    for (const miss of productionCorpus.misses.slice(0, 12)) console.log(miss);
    console.log(
      `TUTULAN: top-1 ${productionHeldout.top1}/${productionHeldout.scored} (${(productionHeldout.rate * 100).toFixed(1)}%)`,
    );
    for (const miss of productionHeldout.misses.slice(0, 12)) console.log(miss);
    console.log(
      `\nGENELLEME PAYI (ÜRETİM): korpus ${(productionCorpus.rate * 100).toFixed(1)}%` +
        ` → tutulan ${(productionHeldout.rate * 100).toFixed(1)}%` +
        ` (fark ${((productionCorpus.rate - productionHeldout.rate) * 100).toFixed(1)} puan)`,
    );
  }
}
