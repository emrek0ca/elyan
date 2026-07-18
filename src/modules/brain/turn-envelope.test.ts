import assert from "node:assert/strict";
import test from "node:test";
import {
  buildTurnEnvelopeResponseFormat,
  claimsConnectorReadWithoutToolRequest,
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

test("parseTurnEnvelope accepts a typed agent plan without treating it as completion", () => {
  const parsed = parseTurnEnvelope({
    reply: { text: "Plan hazır", lang: "tr", tone: "technical" },
    agent_plan: {
      version: "agent_plan.v2",
      goal: { title: "Araştır", success_criteria: ["Kaynak doğrulandı"] },
      steps: [{
        id: "research",
        title: "Kaynak ara",
        depends_on: [],
        tool_request: { tool: "web.search", args: { query: "Elyan" } },
        expected_outcome: {
          description: "Arama başarılı",
          rules: [{ source: "tool_result", path: "ok", operator: "equals", value: true }],
        },
        max_attempts: 3,
      }],
    },
  });
  assert.equal(parsed.ok, true);
  assert.equal(parsed.ok ? parsed.envelope.agent_plan?.steps[0]?.id : null, "research");
});

test("parseTurnEnvelopeText coerces a bare tool-call array into tool_requests (no leak)", () => {
  const result = parseTurnEnvelopeText(
    '[{"tool": "drive.search", "args": {"query": "modifiedTime > 2024", "limit": 20}}]',
  );
  assert.equal(result.ok, true);
  assert.equal(result.ok && result.envelope.tool_requests.length, 1);
  assert.equal(result.ok && result.envelope.tool_requests[0]?.tool, "drive.search");
  // Görünür yanıt boş kalır; tool_requests yürütülür.
  assert.equal(result.ok && result.envelope.reply.text, "");
});

test("parseTurnEnvelopeText strips a ```json code fence before parsing", () => {
  const fenced = '```json\n[{"tool": "drive.search", "args": {"query": "q"}}]\n```';
  const result = parseTurnEnvelopeText(fenced);
  assert.equal(result.ok, true);
  assert.equal(result.ok && result.envelope.tool_requests[0]?.tool, "drive.search");
});

test("parseTurnEnvelope wraps a bare single tool-call object", () => {
  const result = parseTurnEnvelope({ tool: "gmail.search", args: { q: "unread" } });
  assert.equal(result.ok, true);
  assert.equal(result.ok && result.envelope.tool_requests[0]?.tool, "gmail.search");
});

test("looksLikeLeakedToolCallText flags raw tool-call dumps, not normal prose", async () => {
  const { looksLikeLeakedToolCallText } = await import("./turn-envelope.js");
  assert.equal(
    looksLikeLeakedToolCallText('[{"tool":"drive.search","args":{"query":"x"}}]'),
    true,
  );
  assert.equal(
    looksLikeLeakedToolCallText('```json\n{"tool":"x","args":{}}\n```'),
    true,
  );
  assert.equal(looksLikeLeakedToolCallText("Drive'da 3 dosya buldum: rapor, sunum, bütçe."), false);
  assert.equal(looksLikeLeakedToolCallText("[1, 2, 3] listesi hazır."), false);
});

test("claimsConnectorReadWithoutToolRequest catches fabricated mailbox reads", () => {
  const envelope = (
    toolRequests: Array<{ tool: string; args: Record<string, unknown> }>,
  ) => {
    const parsed = parseTurnEnvelope({
      reply: { text: "x", lang: "tr", tone: "neutral" },
      blocks: [],
      memory_ops: [],
      goal_ops: [],
      follow_ups: [],
      tool_requests: toolRequests,
      affect: { user_mood_guess: "nötr", energy: "mid", register: "samimi" },
      proactive_ops: [],
    });
    return parsed.ok ? parsed.envelope : null;
  };

  // Canlıda yakalanan gerçek uydurma cevaplar:
  assert.equal(
    claimsConnectorReadWithoutToolRequest(
      envelope([]),
      "Son e-postanızı okudum. İçeriği şu şekilde: ...",
    ),
    true,
  );
  assert.equal(
    claimsConnectorReadWithoutToolRequest(
      envelope([]),
      "Gelen kutunuzu kontrol ettim, 5 yeni mesaj var.",
    ),
    true,
  );
  assert.equal(
    claimsConnectorReadWithoutToolRequest(envelope([]), "I checked your inbox and found 3 messages."),
    true,
  );
  // Gerçek araç çağrısı varsa iddia meşrudur:
  assert.equal(
    claimsConnectorReadWithoutToolRequest(
      envelope([{ tool: "gmail.search", args: { query: "in:inbox", limit: 5 } }]),
      "Son e-postanızı okudum.",
    ),
    false,
  );
  // Masum metinler tetiklenmez:
  assert.equal(
    claimsConnectorReadWithoutToolRequest(envelope([]), "E-posta yazmak istersen taslak hazırlayabilirim."),
    false,
  );
  assert.equal(claimsConnectorReadWithoutToolRequest(null, "Son e-postanızı okudum."), false);
});

test("looksLikeConnectorPermissionAsk flags consent-seeking pre-tool text", async () => {
  const { looksLikeConnectorPermissionAsk } = await import("./turn-envelope.js");
  // Canlı kanıt turundaki gerçek ön-metin:
  assert.equal(
    looksLikeConnectorPermissionAsk(
      "Son e-postanızı okuyabilmem için Gmail hesabınıza erişim izni gereklidir.",
    ),
    true,
  );
  assert.equal(looksLikeConnectorPermissionAsk("İzin verir misiniz?"), true);
  assert.equal(
    looksLikeConnectorPermissionAsk("I need your permission to access the inbox."),
    true,
  );
  // Gerçek cevaplar tetiklenmez:
  assert.equal(
    looksLikeConnectorPermissionAsk("Gelen kutunda 3 okunmamış mesaj var."),
    false,
  );
  assert.equal(looksLikeConnectorPermissionAsk("Toplantın yarın 14:00'te."), false);
});
