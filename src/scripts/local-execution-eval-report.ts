import {
  SPEECH_ACT_EVAL_CASES,
  type SpeechActEvalCase,
} from "../core/understanding/speech-act-eval-corpus.js";
import { decideLocalExecution } from "../modules/tasks/local-execution-decision.js";
import { warmDesktopCapabilityVectors } from "../modules/tasks/desktop-capability-embedding-match.js";
import {
  primeSemanticComputeWorker,
  resetSemanticComputeWorkerForTests,
} from "../modules/brain/semantic-compute-client.js";

/**
 * YEREL YÜRÜTME KARARI ÖLÇÜM KAPISI.
 *
 * Bu, iki kanıdın BİRLİKTE ne kadar iyi karar verdiğini ölçer. Tek tek
 * ölçümleri `eval:routing` ve `eval:speech-act` veriyor; buradaki soru şu:
 * uzlaşma kuralı, tek sinyalin yapamadığını yapıyor mu?
 *
 * İKİ HATA EŞİT DEĞİLDİR:
 *   * YANLIŞ YÜRÜTME (soru → masaüstü eylemi) canlıda zarar verir. Sıfır olmalı.
 *   * KAÇIRMA (komut → sohbet) can sıkıcıdır ama zararsızdır.
 *
 *   npm run eval:local-execution
 */

// `command` etiketli vakalardan gerçekten YEREL EYLEM olanlar. Şiir/soru/sohbet
// hepsi false. Bu etiketler konuşma eylemi korpusundan BAĞIMSIZ verilir.
const DESKTOP_EXPECTED = new Set<string>([
  "Terminali kapat",
  "Chrome u kapat",
  "Safariden youtube u aç",
  "Masaüstünde deneme123 adında klasör oluştur",
  "Gökhan türkmen den şarkı çal",
  "Müslüm gürsesden bir şeyler çal",
  "Serdar ortaçtan bir şeyler çal",
  "Sezen aksudan bir sarki ac",
  "ekran görüntüsü al",
  "bu dosyayı arşive taşı",
  "spotify aç bakalım",
  "şu pencereyi öne getir",
  "abime whatsapptan selam yolla",
  "perşembe öğlen için ajandama bir şey koy",
]);

type Row = { utterance: string; want: boolean; heldout: boolean };

const rows: Row[] = SPEECH_ACT_EVAL_CASES.map((item: SpeechActEvalCase) => ({
  utterance: item.utterance,
  want: DESKTOP_EXPECTED.has(item.utterance),
  heldout: item.group.startsWith("heldout_"),
}));

async function score(list: Row[]) {
  let correct = 0;
  let dangerous = 0;
  let missed = 0;
  const details: string[] = [];
  for (const row of list) {
    const decision = await decideLocalExecution({
      message: row.utterance,
      timeoutMs: 8_000,
    });
    const got = decision.requiresLocalExecution;
    if (got === row.want) correct += 1;
    else if (got && !row.want) {
      dangerous += 1;
      details.push(
        `  TEHLİKELİ  "${row.utterance}" → masaüstü (${decision.capability}, ${decision.reason})`,
      );
    } else {
      missed += 1;
      details.push(
        `  kaçırma    "${row.utterance}" → sohbet (${decision.reason}, cap=${decision.capability ?? "-"}, act=${decision.speechAct?.act ?? "-"})`,
      );
    }
  }
  return { scored: list.length, correct, dangerous, missed, details };
}

try {
  await primeSemanticComputeWorker({
    modelName:
      process.env.ELYAN_RAG_SEMANTIC_RERANK_MODEL ??
      "intfloat/multilingual-e5-small",
  });
  await warmDesktopCapabilityVectors();

  for (const [name, list] of [
    ["KORPUS", rows.filter((row) => !row.heldout)],
    ["TUTULAN", rows.filter((row) => row.heldout)],
  ] as const) {
    const result = await score(list);
    console.log(`\n===== ${name} (${result.scored} vaka) =====`);
    console.log(
      `doğru ${result.correct}/${result.scored} (${((result.correct / Math.max(1, result.scored)) * 100).toFixed(1)}%)`,
    );
    console.log(`YANLIŞ YÜRÜTME (sıfır olmalı): ${result.dangerous}`);
    console.log(`kaçırma (zararsız):            ${result.missed}`);
    for (const line of result.details) console.log(line);
  }
} finally {
  resetSemanticComputeWorkerForTests();
}
