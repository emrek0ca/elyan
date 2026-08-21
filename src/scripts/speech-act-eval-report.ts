import {
  SPEECH_ACT_EVAL_CASES,
  type SpeechActEvalCase,
} from "../core/understanding/speech-act-eval-corpus.js";
import {
  classifySpeechAct,
  speechActAllowsExecution,
} from "../core/understanding/speech-act.js";
import { primeSemanticComputeWorker } from "../modules/brain/semantic-compute-client.js";
import { resetSemanticComputeWorkerForTests } from "../modules/brain/semantic-compute-client.js";

/**
 * KONUŞMA EYLEMİ ÖLÇÜM KAPISI.
 *
 * Kural (bu projede ihlal edildiğinde canlıya tehlikeli bir kural gitti,
 * 2026-08-22): konuşma eylemi eksenine, yetenek seçimine veya yönlendirmeye
 * dokunan hiçbir değişiklik bu raporu koşmadan çıkmaz.
 *
 *   npm run eval:speech-act
 *
 * TUTULAN kümeye bakıp prototip ayarlamak YASAK — o zaman genelleme payı
 * ölçülemez hale gelir.
 */

type Result = {
  scored: number;
  correct: number;
  executionCorrect: number;
  misses: string[];
};

async function score(cases: SpeechActEvalCase[]): Promise<Result> {
  let correct = 0;
  let executionCorrect = 0;
  const misses: string[] = [];
  for (const item of cases) {
    const decision = await classifySpeechAct(item.utterance, { timeoutMs: 8_000 });
    const got = decision?.act ?? "(karar yok)";
    if (got === item.expected) correct += 1;
    else {
      misses.push(
        `  "${item.utterance}" → bekleniyordu ${item.expected}, geldi ${got}` +
          (decision ? ` (skor ${decision.score.toFixed(3)} marj ${decision.margin.toFixed(3)} ${decision.source})` : ""),
      );
    }
    // ASIL KAPI: yürütmeye izin verilip verilmeyeceği. Bir soruyu "correction"
    // sanmak zararsız; "command" sanmak canlıda Chrome'u kapatır.
    const wantExecution = speechActAllowsExecution(item.expected);
    const gotExecution = speechActAllowsExecution(decision?.act ?? null);
    if (wantExecution === gotExecution) executionCorrect += 1;
  }
  return { scored: cases.length, correct, executionCorrect, misses };
}

function pct(part: number, total: number): string {
  return total === 0 ? "0.0%" : `${((part / total) * 100).toFixed(1)}%`;
}

const corpus = SPEECH_ACT_EVAL_CASES.filter((item) => !item.group.startsWith("heldout_"));
const heldout = SPEECH_ACT_EVAL_CASES.filter((item) => item.group.startsWith("heldout_"));

try {
  await primeSemanticComputeWorker({
    modelName:
      process.env.ELYAN_RAG_SEMANTIC_RERANK_MODEL ??
      "intfloat/multilingual-e5-small",
  });

  for (const [name, cases] of [
    ["KORPUS", corpus],
    ["TUTULAN", heldout],
  ] as const) {
    const result = await score(cases);
    console.log(`\n===== ${name} (${result.scored} vaka) =====`);
    console.log(`konuşma eylemi doğruluğu   ${result.correct}/${result.scored} (${pct(result.correct, result.scored)})`);
    console.log(`YÜRÜTME KAPISI doğruluğu   ${result.executionCorrect}/${result.scored} (${pct(result.executionCorrect, result.scored)})`);
    if (result.misses.length > 0) {
      console.log("hatalar:");
      for (const miss of result.misses) console.log(miss);
    }
  }

  // MARJ DAĞILIMI — yürütme eşiğini KORPUS verisinden seçmek için.
  // Tutulan kümeye bakıp eşik ayarlamak yasak; bu blok yalnız korpusu okur.
  const commandMargins: number[] = [];
  const nonCommandAsCommandMargins: number[] = [];
  for (const item of corpus) {
    const decision = await classifySpeechAct(item.utterance, { timeoutMs: 8_000 });
    if (!decision || decision.source === "punctuation") continue;
    if (item.expected === "command" && decision.act === "command") {
      commandMargins.push(decision.margin);
    }
    if (item.expected !== "command" && decision.act === "command") {
      nonCommandAsCommandMargins.push(decision.margin);
    }
  }
  const fmt = (values: number[]) =>
    values.length === 0
      ? "-"
      : `n=${values.length} min=${Math.min(...values).toFixed(3)} med=${[...values]
          .sort((a, b) => a - b)[Math.floor(values.length / 2)].toFixed(3)} max=${Math.max(...values).toFixed(3)}`;
  console.log("\n===== MARJ DAĞILIMI (korpus) =====");
  console.log(`gerçek komutlar          ${fmt(commandMargins)}`);
  console.log(`komut sanılan komut-dışı ${fmt(nonCommandAsCommandMargins)}`);

  // Kritik alt küme: komutla aynı komşulukta duran sorular. Canlı arızanın
  // sınıfı budur ve tek başına raporlanmalı.
  const nearMiss = corpus.filter((item) => item.group === "question_near_command");
  const nearResult = await score(nearMiss);
  console.log(`\n===== KRİTİK: komut komşuluğundaki sorular (${nearResult.scored}) =====`);
  console.log(
    `yürütmeye izin verilmemeli → doğru ${nearResult.executionCorrect}/${nearResult.scored} (${pct(nearResult.executionCorrect, nearResult.scored)})`,
  );
} finally {
  resetSemanticComputeWorkerForTests();
}
