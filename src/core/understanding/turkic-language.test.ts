import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTurkicWebQueryVariants,
  detectTurkicLanguagePreference,
  getTurkicLanguagePromptHint,
} from "./turkic-language.js";

test("detectTurkicLanguagePreference recognizes natural Turkish messages", () => {
  assert.equal(
    detectTurkicLanguagePreference("Merhaba Elyan, bunu daha profesyonel ve kisa yaz."),
    "Turkish",
  );
});

test("detectTurkicLanguagePreference recognizes Turkic language family prompts", () => {
  assert.equal(
    detectTurkicLanguagePreference("Oğuz, Kıpçak ve Karluk dillerini araştır ve karşılaştır."),
    "Turkic",
  );
});

test("buildTurkicWebQueryVariants keeps Turkish and Turkic prefixes available", () => {
  const variants = buildTurkicWebQueryVariants("Oğuz, Kıpçak ve Karluk dillerini araştır ve karşılaştır.");

  assert.ok(variants.some((variant) => variant.includes("Türk dünyası")));
  assert.ok(variants.some((variant) => variant.includes("Turkic languages")));
});

test("getTurkicLanguagePromptHint returns a safe language hint", () => {
  const hint = getTurkicLanguagePromptHint("Lütfen Türkçe yanıt ver.");

  assert.ok(hint?.includes("polished standard Turkish"));
  assert.ok(hint?.includes("Turkish"));
});
