import assert from "node:assert/strict";
import test from "node:test";
import {
  buildMemoryProfilePromptBlock,
  buildPreferencePromptBlock,
  formatPreferencePromptValue,
} from "./preference-prompt.js";

test("formatPreferencePromptValue localizes known preference values", () => {
  assert.equal(formatPreferencePromptValue("preferred_language", "turkish"), "Türkçe");
  assert.equal(formatPreferencePromptValue("preferred_tone", "warm_professional"), "Sıcak ve profesyonel");
  assert.equal(formatPreferencePromptValue("answer_length", "concise"), "Kısa ve öz");
  assert.equal(formatPreferencePromptValue("custom", "plain"), "Plain");
});

test("buildPreferencePromptBlock renders safe user preference hints and deduplicates", () => {
  const block = buildPreferencePromptBlock({
    memoryEnabled: true,
    personalizationPrompt: "Kısa ve net cevap ver",
    dialogueUserMemory: {
      name: null,
      preferredName: "Emre",
      preferredLanguage: "turkish",
      preferredTone: "warm_professional",
      responseStyle: null,
      timezone: null,
      updatedAt: new Date().toISOString(),
    },
    memorySnapshot: {
      preferenceFacts: [
        { key: "preferred_language", value: "turkish" },
        { key: "preferred_tone", value: "warm_professional" },
        { key: "answer_length", value: "concise" },
      ],
    },
    personalizationHints: ["Kısa ve net cevap ver", "Kısa ve net cevap ver"],
    styleHints: ["Madde madde yaz", "Gereksiz giriş yapma"],
    safetyHints: ["Özel veriyi loglama"],
    relationshipContextDigest: ["Kullanıcı backend mimarisine odaklanıyor"],
    speakingStyleDirectives: ["Türkçe konuş"],
    behavioralHints: ["Hızlı başla"],
    environmentHints: ["Mobil bağlam olabilir"],
  } as never);

  assert.ok(block?.startsWith("User preference hints:"));
  assert.match(block ?? "", /Memory is enabled for this user/);
  assert.match(block ?? "", /Current dialogue state preferred name: Emre/);
  assert.match(block ?? "", /Current dialogue state preferred language: Türkçe/);
  assert.match(block ?? "", /Current dialogue state style: tone=Sıcak ve profesyonel/);
  assert.match(block ?? "", /Preferred language: Türkçe/);
  assert.match(block ?? "", /Response style preference: Sıcak ve profesyonel/);
  assert.match(block ?? "", /Answer length preference: Kısa ve öz/);
  assert.equal((block?.match(/- Kısa ve net cevap ver/g) ?? []).length, 1);
});

test("buildPreferencePromptBlock reflects memory disabled mode", () => {
  const block = buildPreferencePromptBlock({
    memoryEnabled: false,
  } as never);

  assert.match(block ?? "", /Memory is disabled for this request/);
});

test("buildMemoryProfilePromptBlock delegates memory snapshot formatting", () => {
  const block = buildMemoryProfilePromptBlock({
    memorySnapshot: {
      summary: "Hatırlanan çekirdek: tercih=Tercih edilen dil: turkish",
      identityFacts: [],
      preferenceFacts: [
        {
          key: "preferred_language",
          label: "Tercih edilen dil",
          value: "turkish",
          confidence: 0.9,
          source: "semantic_memory",
          staleness: "fresh",
          updatedAt: new Date().toISOString(),
        },
      ],
      projectFacts: [],
      derivedFacts: [],
      recentEpisodes: [],
      safetyNotes: [],
      memoryCount: 1,
      compactedCount: 0,
      lastUpdatedAt: new Date().toISOString(),
    },
  } as never);

  assert.match(block ?? "", /User memory profile/);
  assert.match(block ?? "", /Tercih edilen dil/);
});
