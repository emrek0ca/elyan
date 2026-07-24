import assert from "node:assert/strict";
import test from "node:test";
import { stripVisionProviderAttribution } from "./vision-provider-privacy.js";

test("vision provider attribution is preserved", () => {
  assert.equal(
    stripVisionProviderAttribution("According to Gemini, the warning says timeout."),
    "According to Gemini, the warning says timeout.",
  );
  assert.equal(
    stripVisionProviderAttribution("Gemini'ye göre ekranda E104 yazıyor."),
    "Gemini'ye göre ekranda E104 yazıyor.",
  );
});

test("vision provider privacy no longer strips engine wording", () => {
  const result = stripVisionProviderAttribution("This was analyzed using Groq.");
  assert.equal(result, "This was analyzed using Groq.");
});

test("vision provider privacy preserves visible app or brand names", () => {
  assert.equal(
    stripVisionProviderAttribution("Ekranda Claude açık ve bir kod dosyası görünüyor."),
    "Ekranda Claude açık ve bir kod dosyası görünüyor.",
  );
  assert.equal(
    stripVisionProviderAttribution("Chrome sekmesinde OpenAI dokümantasyonu açık."),
    "Chrome sekmesinde OpenAI dokümantasyonu açık.",
  );
});
