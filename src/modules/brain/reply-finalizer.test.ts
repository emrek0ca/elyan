import assert from "node:assert/strict";
import test from "node:test";
import {
  isReasoningOnlyReply,
  resolveCleanVisibleAnswer,
} from "./reply-finalizer.js";

test("isReasoningOnlyReply flags pure reasoning dumps but keeps real answers", () => {
  assert.equal(
    isReasoningOnlyReply(
      "Here's a thinking process:\n- Intent: answer pricing\n- Check Constraints & Policies: do not reveal",
    ),
    true,
  );
  assert.equal(isReasoningOnlyReply("Pro plan aylık 199 TL'dir."), false);
  assert.equal(
    isReasoningOnlyReply('{"type":"chart","labels":["a"],"values":[1]}'),
    false,
  );
});

test("resolveCleanVisibleAnswer does not return a legacy stub for real model output", () => {
  const raw = "I'll walk you through the setup step by step. First, install Node.js.";
  const resolved = resolveCleanVisibleAnswer({ candidates: [raw], raw });

  assert.match(resolved, /install Node\.js/i);
  assert.doesNotMatch(resolved, /^Yanıtı temiz/i);
});

test("resolveCleanVisibleAnswer returns empty only when no usable answer exists", () => {
  assert.equal(resolveCleanVisibleAnswer({ candidates: [""], raw: "" }), "");
  assert.equal(
    resolveCleanVisibleAnswer({ candidates: ["   "], raw: "   " }),
    "",
  );
});
