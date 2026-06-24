import assert from "node:assert/strict";
import test from "node:test";
import { buildSharedBrainAckText, selectHybridMobileChatWorkload } from "./chat-heuristics.js";

test("buildSharedBrainAckText returns empty string so frontend loading indicator handles pending state", () => {
  // All workloads must return empty — no "Bir saniye bakıyorum" injected into
  // the assistant message before the real answer arrives.
  assert.equal(buildSharedBrainAckText("mobile_chat_fast"), "");
  assert.equal(buildSharedBrainAckText("mobile_chat_balanced"), "");
  assert.equal(buildSharedBrainAckText("planning"), "");
});

test("selectHybridMobileChatWorkload keeps only greetings on fast and upgrades explanatory asks", () => {
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Selam",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_fast",
  );
  assert.equal(
    selectHybridMobileChatWorkload({
      message: "Bunu neden böyle yaptığını kısa ama net şekilde açıkla.",
      primaryIntent: "chat",
      brainProfile: null,
    }),
    "mobile_chat_balanced",
  );
});
