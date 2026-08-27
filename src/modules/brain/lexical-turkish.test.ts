import assert from "node:assert/strict";
import test from "node:test";
import {
  contentTerms,
  foldTurkish,
  jaccardSimilarity,
  stemTurkish,
} from "./lexical-turkish.js";

test("Turkish folding collapses the i family onto a single letter", () => {
  assert.equal(foldTurkish("İSTANBUL"), "istanbul");
  assert.equal(foldTurkish("Işık"), "işik");
  assert.equal(foldTurkish("ATATÜRK"), "atatürk");
});

test("inflected forms of the same concept reduce to one key", () => {
  const stem = stemTurkish("ilke");
  for (const variant of ["ilkeleri", "ilkelerin", "ilkeler", "İlkeleri"]) {
    assert.equal(
      stemTurkish(variant).startsWith(stem),
      true,
      `${variant} should share a stem with ilke`,
    );
  }
  // Kısa kelimeler budanmaz: ek, kelimenin kendisini yiyemez.
  assert.equal(stemTurkish("yaz"), "yaz");
  assert.equal(stemTurkish("veri"), "veri");
});

test("terms survive inflection so the same concept matches across forms", () => {
  const asked = new Set(contentTerms("Atatürk'ün ilkeleri neler"));
  const stored = new Set(contentTerms("Atatürk ilkeler üzerine not"));
  let shared = 0;
  for (const term of asked) if (stored.has(term)) shared += 1;
  // Eskiden tam-token karşılaştırmasıydı ve bu iki metin HİÇ örtüşmüyordu.
  assert.equal(shared >= 2, true);
});

test("an apostrophe separates a proper noun from its suffix", () => {
  assert.equal(contentTerms("Atatürk'ün").length, 1);
  assert.equal(contentTerms("Atatürk'ün")[0], contentTerms("Atatürk")[0]);
});

test("jaccard similarity is symmetric and length-fair", () => {
  const left = new Set(["a", "b", "c"]);
  const right = new Set(["b", "c", "d"]);
  assert.equal(jaccardSimilarity(left, right), jaccardSimilarity(right, left));
  assert.equal(jaccardSimilarity(left, right), 0.5);
  assert.equal(jaccardSimilarity(left, new Set()), 0);
  assert.equal(jaccardSimilarity(left, new Set(left)), 1);
});
