import assert from "node:assert/strict";
import test from "node:test";
import {
  agentToolResultDigest,
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

test("agentToolResultDigest is stable across object key order", () => {
  const left = {
    tool: "web.numeric_facts",
    ok: true,
    permission: "read" as const,
    durationMs: 1,
    output: { points: [{ value: 2, label: "b" }], query: "q" },
    error: null,
  };
  const right = {
    ...left,
    durationMs: 999,
    output: { query: "q", points: [{ label: "b", value: 2 }] },
  };
  assert.equal(agentToolResultDigest(left), agentToolResultDigest(right));
  assert.match(agentToolResultDigest(left), /^[a-f0-9]{32}$/);
});

test("legacy agent_plan.v2 executes dependent steps in order and verifies each result", async () => {
  const originalFetch = globalThis.fetch;
  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(
      `<html><head><title>Test</title></head><body><article>${"verified ".repeat(40)}</article></body></html>`,
      { status: 200, headers: { "content-type": "text/html" } },
    );
  }) as typeof fetch;
  try {
    const requests = [
      { tool: "web.fetch_url", args: { url: "https://example.com/first" } },
      { tool: "web.fetch_url", args: { url: "https://example.com/second" } },
    ];
    const result = await runAgentToolLoop(
      {
        config: { JINA_READER_ENABLED: false },
        log: { info() {} },
      } as never,
      {
        context: { userId: "user-1", workload: "mobile_chat_fast" },
        requests,
        plan: {
          version: "agent_plan.v2",
          goal: {
            title: "Read two pages",
            success_criteria: ["Both reads are verified."],
          },
          steps: [
            {
              id: "first",
              title: "Read first page",
              depends_on: [],
              tool_request: requests[0],
              expected_outcome: {
                description: "First read succeeds",
                rules: [
                  {
                    source: "tool_result",
                    path: "ok",
                    operator: "equals",
                    value: true,
                  },
                ],
              },
              max_attempts: 1,
            },
            {
              id: "second",
              title: "Read second page",
              depends_on: ["first"],
              tool_request: requests[1],
              expected_outcome: {
                description: "Second read succeeds",
                rules: [
                  {
                    source: "tool_result",
                    path: "ok",
                    operator: "equals",
                    value: true,
                  },
                ],
              },
              max_attempts: 1,
            },
          ],
        },
      },
    );

    assert.deepEqual(calls, [
      "https://example.com/first",
      "https://example.com/second",
    ]);
    assert.equal(result.planVersion, "agent_plan.v2");
    assert.equal(result.verificationPassed, true);
    assert.equal(result.results.length, 2);
    assert.equal(result.results.every((item) => item.ok), true);
    assert.equal(
      result.stepVerifications?.every((item) => item.passed),
      true,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("legacy agent_plan.v2 stops dependent work after failed verification", async () => {
  const originalFetch = globalThis.fetch;
  let callCount = 0;
  globalThis.fetch = (async () => {
    callCount += 1;
    return new Response(
      "<html><head><title>Test</title></head><body><article>short but valid content for the test page</article></body></html>",
      { status: 200, headers: { "content-type": "text/html" } },
    );
  }) as typeof fetch;
  try {
    const requests = [
      { tool: "web.fetch_url", args: { url: "https://example.net/first" } },
      { tool: "web.fetch_url", args: { url: "https://example.net/second" } },
    ];
    const result = await runAgentToolLoop(
      {
        config: { JINA_READER_ENABLED: false },
        log: { info() {} },
      } as never,
      {
        context: { userId: "user-1", workload: "mobile_chat_fast" },
        requests,
        plan: {
          version: "agent_plan.v2",
          goal: {
            title: "Fail closed",
            success_criteria: ["Do not continue after unverifiable data."],
          },
          steps: [
            {
              id: "first",
              title: "Require impossible length",
              depends_on: [],
              tool_request: requests[0],
              expected_outcome: {
                description: "The page is unexpectedly large",
                rules: [
                  {
                    source: "tool_result",
                    path: "output.contentLength",
                    operator: "gte",
                    value: 9_999,
                  },
                ],
              },
              max_attempts: 1,
            },
            {
              id: "second",
              title: "Must not run",
              depends_on: ["first"],
              tool_request: requests[1],
              expected_outcome: {
                description: "Second read succeeds",
                rules: [
                  {
                    source: "tool_result",
                    path: "ok",
                    operator: "equals",
                    value: true,
                  },
                ],
              },
              max_attempts: 1,
            },
          ],
        },
      },
    );

    assert.equal(callCount, 1);
    assert.equal(result.verificationPassed, false);
    assert.equal(result.results.length, 1);
    assert.equal(result.results[0]?.ok, false);
    assert.equal(
      result.results[0]?.error?.code,
      "tool_verification_failed",
    );
    assert.equal(result.stepVerifications?.[0]?.passed, false);
  } finally {
    globalThis.fetch = originalFetch;
  }
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
