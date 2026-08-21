import assert from "node:assert/strict";
import test from "node:test";
import {
  hasExplicitQuestionMark,
  speechActAllowsExecution,
  speechActValues,
} from "./speech-act.js";
import { SPEECH_ACT_EVAL_CASES } from "./speech-act-eval-corpus.js";

// ---------------------------------------------------------------------------
// Konuşma eylemi ekseni KANITTIR, YETKİ DEĞİL.
//
// Ölçüm (npm run eval:speech-act, 2026-08-22):
//   korpus  %53.8 → %96.2   (tek uzun açıklama → kısa örnek listesi)
//   tutulan %25.0 → %66.7
//   marj dağılımı ÇAKIŞIYOR: gerçek komutlar min 0.002, yanlış-pozitif 0.019
//     → eşikle ayrılamaz; bu yüzden tek başına yürütme kapısı OLAMAZ.
// ---------------------------------------------------------------------------

test("question marks are a language-independent, high-precision signal", () => {
  assert.equal(hasExplicitQuestionMark("Chrome nedir?"), true);
  assert.equal(hasExplicitQuestionMark("bu ne işe yarar? "), true);
  assert.equal(hasExplicitQuestionMark("Chrome'u kapat"), false);
  assert.equal(hasExplicitQuestionMark(""), false);
});

test("only genuine work requests may unlock execution", () => {
  assert.equal(speechActAllowsExecution("command"), true);
  assert.equal(speechActAllowsExecution("confirmation"), true);
  assert.equal(speechActAllowsExecution("correction"), true);
  // Kritik: soru ve sohbet ASLA yürütme açmaz.
  assert.equal(speechActAllowsExecution("question"), false);
  assert.equal(speechActAllowsExecution("statement"), false);
  // Karar verilemediyse fail-closed.
  assert.equal(speechActAllowsExecution(null), false);
  assert.equal(speechActAllowsExecution(undefined), false);
});

test("the eval corpus keeps a real held-out split", () => {
  const heldout = SPEECH_ACT_EVAL_CASES.filter((item) =>
    item.group.startsWith("heldout_"),
  );
  const corpus = SPEECH_ACT_EVAL_CASES.filter(
    (item) => !item.group.startsWith("heldout_"),
  );
  assert.ok(corpus.length >= 20, `korpus çok küçük: ${corpus.length}`);
  assert.ok(heldout.length >= 8, `tutulan küme çok küçük: ${heldout.length}`);
  // Tutulan küme korpusla ÇAKIŞMAMALI — çakışırsa genelleme payı sahte olur.
  const corpusText = new Set(corpus.map((item) => item.utterance.toLowerCase()));
  for (const item of heldout) {
    assert.equal(
      corpusText.has(item.utterance.toLowerCase()),
      false,
      `tutulan vaka korpusta da var: ${item.utterance}`,
    );
  }
  for (const item of SPEECH_ACT_EVAL_CASES) {
    assert.ok(
      speechActValues.includes(item.expected),
      `bilinmeyen etiket: ${item.expected}`,
    );
  }
});

test("the corpus contains the live failure class that motivated this axis", () => {
  const nearCommand = SPEECH_ACT_EVAL_CASES.filter(
    (item) => item.group === "question_near_command",
  );
  assert.ok(nearCommand.length >= 5);
  // Canlıda Chrome'u kapatabilecek olan cümle korpusta durmalı.
  assert.ok(
    nearCommand.some((item) => item.utterance.toLowerCase().includes("chrome nedir")),
  );
  assert.ok(nearCommand.every((item) => item.expected === "question"));
});
