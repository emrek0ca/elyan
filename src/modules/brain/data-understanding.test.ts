import assert from "node:assert/strict";
import test from "node:test";
import {
  detectPromptLanguage,
  inferDataGroundingLevel,
} from "./data-understanding.js";

test("detectPromptLanguage keeps existing Turkish, English, mixed, and unknown decisions", () => {
  assert.equal(detectPromptLanguage("Selam, bunu özetle"), "tr");
  assert.equal(detectPromptLanguage("How should I summarize this document?"), "en");
  assert.equal(detectPromptLanguage("Bu document nasıl fix edilir?"), "mixed");
  assert.equal(detectPromptLanguage("12345"), "unknown");
});

test("detectPromptLanguage recognizes Turkic-family prompts without Turkish wording", () => {
  assert.equal(detectPromptLanguage("özbek ve kazak karşılaştırması"), "tr");
  assert.equal(detectPromptLanguage("kazak kyrgyz language family"), "turkic");
  assert.equal(detectPromptLanguage("kazak kırgız language family"), "tr");
});

test("inferDataGroundingLevel prioritizes attachments, then memory-derived context", () => {
  assert.equal(
    inferDataGroundingLevel({
      attachmentContext: { used: true },
      understandingContext: {
        contextPackets: [],
        retrievedMemory: [],
      } as never,
    }),
    "attachment_grounded",
  );
  assert.equal(
    inferDataGroundingLevel({
      attachmentContext: { used: false },
      understandingContext: {
        contextPackets: [{ kind: "time_context" }],
        retrievedMemory: [],
      } as never,
    }),
    "memory_augmented",
  );
  assert.equal(
    inferDataGroundingLevel({
      attachmentContext: null,
      understandingContext: {
        contextPackets: [],
        retrievedMemory: [{ id: "mem_1" }],
      } as never,
    }),
    "memory_augmented",
  );
  assert.equal(inferDataGroundingLevel({}), "request_only");
});
