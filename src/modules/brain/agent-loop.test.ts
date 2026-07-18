import assert from "node:assert/strict";
import test from "node:test";
import {
  buildToolResultRefinementPrompt,
  runAgentToolLoop,
  summarizeToolResultsForMetadata,
  trimEnumeratedListForStructuredCard,
} from "./agent-loop.js";

test("runAgentToolLoop executes bounded tool requests and summarizes safe metadata", async () => {
  const result = await runAgentToolLoop({} as never, {
    context: {
      userId: "user-1",
      workload: "mobile_chat_fast",
    },
    maxRequests: 2,
    requests: [
      { tool: "not.real.one", args: {} },
      { tool: "not.real.two", args: {} },
      { tool: "not.real.three", args: {} },
    ],
  });

  assert.equal(result.iterations, 1);
  assert.equal(result.results.length, 2);
  assert.equal(result.timedOut, false);
  const summary = summarizeToolResultsForMetadata(result.results);
  assert.deepEqual(
    summary.map((item) => item.errorCode),
    ["unknown_tool", "unknown_tool"],
  );
});

test("buildToolResultRefinementPrompt carries typed tool results without long raw dumps", () => {
  const prompt = buildToolResultRefinementPrompt({
    originalPrompt: "Altın fiyatını araştır",
    results: [
      {
        tool: "web.search",
        ok: true,
        permission: "read",
        durationMs: 12,
        error: null,
        output: {
          results: [
            {
              title: "Kaynak",
              snippet: "x".repeat(2_000),
            },
          ],
        },
      },
    ],
  });

  assert.equal(prompt.includes("Altın fiyatını araştır"), true);
  assert.equal(prompt.includes("web.search"), true);
  assert.match(prompt, /Return only the user-facing answer/);
  assert.match(prompt, /group and deduplicate/);
  assert.equal(prompt.length < 9_000, true);
});

test("buildToolResultRefinementPrompt: kart render edilecekse enumerasyonu yasaklar", () => {
  const prompt = buildToolResultRefinementPrompt({
    originalPrompt: "Mailleri oku",
    results: [
      {
        tool: "gmail.search",
        ok: true,
        permission: "read",
        durationMs: 20,
        output: { results: [{ subject: "A" }, { subject: "B" }] },
        error: null,
      },
    ],
    structuredBlocksWillRender: true,
  });
  assert.match(prompt, /Do NOT enumerate the items/);
  assert.match(prompt, /1-2 sentences/);
  assert.doesNotMatch(prompt, /group and deduplicate/);
});

test("trimEnumeratedListForStructuredCard: 3+ satırlık listeyi kırpar, girişi korur", () => {
  const text = [
    "Gelen kutunda 5 yeni e-posta var, çoğu LinkedIn bildirimi.",
    "",
    "1. **Glassdoor** – Java rolü – 18 Tem",
    "2. **Product Hunt** – Japan – 18 Tem",
    "3. **LinkedIn** – başvuru – 18 Tem",
  ].join("\n");
  assert.equal(
    trimEnumeratedListForStructuredCard(text),
    "Gelen kutunda 5 yeni e-posta var, çoğu LinkedIn bildirimi.",
  );
  // Giriş yoksa boş döner (kart tek başına durur).
  assert.equal(
    trimEnumeratedListForStructuredCard("- a\n- b\n- c"),
    "",
  );
  // Kısa (1-2 maddelik) listeler meşru cevap olabilir: dokunma.
  const short = "Özet:\n1. tek madde\n2. iki madde";
  assert.equal(trimEnumeratedListForStructuredCard(short), short);
});
