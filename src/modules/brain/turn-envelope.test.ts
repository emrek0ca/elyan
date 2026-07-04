import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTurnEnvelopeResponseFormat,
  looksLikeTurnEnvelopeJson,
  parseTurnEnvelope,
  parseTurnEnvelopeText,
} from "./turn-envelope.js";

test("parseTurnEnvelope accepts typed reply, blocks, ops, follow-ups, and tools", () => {
  const result = parseTurnEnvelope({
    reply: { text: "Selam Emre.", lang: "tr", tone: "warm" },
    blocks: [{ type: "text", markdown: "Selam Emre." }],
    memory_ops: [
      {
        op: "write",
        kind: "preference",
        key: "address_name",
        value: "Emre",
        confidence: 0.92,
      },
    ],
    goal_ops: [{ op: "advance", step: "F2", next: "stream parser" }],
    follow_ups: [{ due: "tomorrow", topic: "deploy", nudge: "Deploy nasıl gitti?" }],
    tool_requests: [{ tool: "web.search", args: { q: "Elyan" } }],
    affect: { user_mood_guess: "focused", energy: "high", register: "technical" },
  });

  assert.equal(result.ok, true);
  assert.equal(result.ok && result.envelope.reply.text, "Selam Emre.");
  assert.equal(result.ok && result.envelope.blocks[0]?.type, "text");
  assert.equal(result.ok && result.envelope.memory_ops.length, 1);
  assert.equal(result.ok && result.envelope.follow_ups.length, 1);
});

test("parseTurnEnvelope defaults missing arrays without accepting invalid blocks", () => {
  const minimal = parseTurnEnvelopeText(
    JSON.stringify({
      reply: { text: "Kısa cevap.", lang: "tr", tone: "neutral" },
      affect: { user_mood_guess: "unknown", energy: "mid", register: "neutral" },
    }),
  );
  assert.equal(minimal.ok, true);
  assert.deepEqual(minimal.ok ? minimal.envelope.blocks : null, []);

  const invalidBlock = parseTurnEnvelope({
    reply: { text: "Tablo hazırladım.", lang: "tr", tone: "technical" },
    blocks: [{ type: "table" }],
    memory_ops: [],
    goal_ops: [],
    follow_ups: [],
    tool_requests: [],
    affect: { user_mood_guess: "unknown", energy: "mid", register: "technical" },
  });
  assert.equal(invalidBlock.ok, false);
});

test("parseTurnEnvelope accepts provider output containing only the required reply", () => {
  const result = parseTurnEnvelopeText(
    '{"reply":{"lang":"tr","text":"Merhaba!","tone":"warm"}}',
  );

  assert.equal(result.ok, true);
  assert.deepEqual(result.ok ? result.envelope.memory_ops : null, []);
  assert.deepEqual(result.ok ? result.envelope.goal_ops : null, []);
  assert.deepEqual(result.ok ? result.envelope.follow_ups : null, []);
  assert.deepEqual(result.ok ? result.envelope.tool_requests : null, []);
});

test("parseTurnEnvelope accepts typed forget operations without memory content", () => {
  const result = parseTurnEnvelope({
    reply: { text: "Tamam, bunu unuttum.", lang: "tr", tone: "warm" },
    memory_ops: [
      {
        op: "forget",
        kind: "preference",
        key: "preferred_name",
        confidence: 1,
      },
    ],
  });

  assert.equal(result.ok, true);
  assert.equal(result.ok ? result.envelope.memory_ops[0]?.op : null, "forget");
  assert.equal(result.ok ? result.envelope.memory_ops[0]?.value : null, "");
});

test("parseTurnEnvelope accepts typed proactive preference operations", () => {
  const result = parseTurnEnvelope({
    reply: { text: "Tamam.", lang: "tr", tone: "warm" },
    proactive_ops: [{ op: "mute", kind: "follow_up" }],
  });
  assert.equal(result.ok, true);
  assert.equal(result.ok ? result.envelope.proactive_ops?.[0]?.op : null, "mute");
});

test("parseTurnEnvelope accepts ISO date-only follow-up due values", () => {
  const result = parseTurnEnvelope({
    reply: { text: "Yarın soracağım.", lang: "tr", tone: "warm" },
    follow_ups: [
      {
        due: "2030-01-02",
        topic: "Altyapı testi",
        nudge: "Altyapı testi nasıl gitti?",
      },
    ],
  });

  assert.equal(result.ok, true);
  assert.equal(
    result.ok ? result.envelope.follow_ups[0]?.due : null,
    "2030-01-02",
  );
});

test("turn envelope helpers detect envelope-shaped JSON and expose provider schema", () => {
  assert.equal(
    looksLikeTurnEnvelopeJson(
      '{"reply":{"text":"x"},"memory_ops":[],"goal_ops":[],"follow_ups":[]}',
    ),
    true,
  );
  const responseFormat = buildTurnEnvelopeResponseFormat();
  assert.equal(responseFormat.type, "json_schema");
  const jsonSchema = responseFormat.json_schema as Record<string, unknown>;
  assert.equal(jsonSchema.name, "elyan_turn_envelope");
  assert.equal(jsonSchema.strict, false);
  const schema = jsonSchema.schema as Record<string, unknown>;
  assert.equal((schema.required as string[]).includes("proactive_ops"), false);
  const proactiveFormat = buildTurnEnvelopeResponseFormat(true);
  const proactiveSchema = (proactiveFormat.json_schema as Record<string, unknown>).schema as Record<string, unknown>;
  assert.equal((proactiveSchema.required as string[]).includes("proactive_ops"), true);
});
