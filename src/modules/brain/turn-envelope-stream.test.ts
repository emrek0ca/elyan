import assert from "node:assert/strict";
import test from "node:test";
import { createTurnEnvelopeReplyTextStreamParser } from "./turn-envelope-stream.js";

test("turn envelope stream parser emits only growing reply.text deltas", () => {
  const parser = createTurnEnvelopeReplyTextStreamParser();
  const chunks = [
    '{"reply":{"text":"Sel',
    "am ",
    'Emre',
    '","lang":"tr","tone":"warm"},"memory_ops":[{"op":"write"}]}',
  ];
  const deltas = chunks.map((chunk) => parser.push(chunk).delta).join("");

  assert.equal(deltas, "Selam Emre");
  assert.equal(parser.finish().text, "Selam Emre");
});

test("turn envelope stream parser decodes escaped content without leaking raw JSON", () => {
  const parser = createTurnEnvelopeReplyTextStreamParser();
  const emitted: string[] = [];
  for (const chunk of [
    '{"reply":{"text":"İlk satır',
    '\\nikinci \\"satır\\"',
    '","lang":"tr","tone":"neutral"},"tool_requests":[{"tool":"web.search","args":{}}]}',
  ]) {
    emitted.push(parser.push(chunk).delta);
  }
  const visible = emitted.join("");

  assert.equal(visible, 'İlk satır\nikinci "satır"');
  assert.equal(visible.includes("tool_requests"), false);
  assert.equal(visible.includes("{"), false);
});

test("turn envelope stream parser fails closed on non-monotonic decoded text", () => {
  const parser = createTurnEnvelopeReplyTextStreamParser();
  assert.equal(parser.push('{"reply":{"text":"Merhaba').delta, "Merhaba");
  const broken = parser.push('","lang":"tr"},"reply":{"text":"X"}').failed;
  assert.equal(broken, false);
  assert.equal(parser.finish().text, "Merhaba");
});
