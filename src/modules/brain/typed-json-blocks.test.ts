import assert from "node:assert/strict";
import test from "node:test";
import {
  computeStreamVisibleText,
  extractTypedJsonBlocksFromText,
} from "./typed-json-blocks.js";

test("computeStreamVisibleText hides complete typed JSON fences", () => {
  const full = 'Cevap:\n```json\n{"type":"table","rows":[["a"]]}\n```\nBitti';
  assert.equal(computeStreamVisibleText(full), "Cevap:\n\nBitti");
});

test("computeStreamVisibleText holds back incomplete JSON objects", () => {
  assert.equal(computeStreamVisibleText('Başla {"type":"table"'), "Başla");
});

test("computeStreamVisibleText unwraps plain brace-wrapped sentences", () => {
  assert.equal(
    computeStreamVisibleText('{"Sadece düz bir cümle"}'),
    "Sadece düz bir cümle",
  );
});

test("computeStreamVisibleText keeps ordinary prose braces visible", () => {
  assert.equal(
    computeStreamVisibleText("Küme gösterimi {1, 2, 3} biçimindedir."),
    "Küme gösterimi {1, 2, 3} biçimindedir.",
  );
});

test("extractTypedJsonBlocksFromText pulls a fenced typed block and leaves prose", () => {
  const { visibleText, blocks } = extractTypedJsonBlocksFromText(
    'Özet:\n```json\n{"type":"document_block","content":"Merhaba"}\n```',
  );

  assert.equal(visibleText, "Özet:");
  assert.deepEqual(blocks, [{ type: "document_block", content: "Merhaba" }]);
});

test("extractTypedJsonBlocksFromText repairs loose control characters in JSON strings", () => {
  const { visibleText, blocks } = extractTypedJsonBlocksFromText(
    '{"type":"document_block","content":"satır1\n\n- madde"}',
  );

  assert.equal(visibleText, "");
  assert.deepEqual(blocks, [
    { type: "document_block", content: "satır1\n\n- madde" },
  ]);
});

test("extractTypedJsonBlocksFromText coerces malformed typed blocks without leaking raw JSON", () => {
  const { visibleText, blocks } = extractTypedJsonBlocksFromText(
    'Başlık {"type":"math","expression":"x^2","displayMode\\frac{dy}{dx}',
  );

  assert.equal(visibleText, "Başlık");
  assert.deepEqual(blocks, [{ type: "math", expression: "x^2" }]);
});
