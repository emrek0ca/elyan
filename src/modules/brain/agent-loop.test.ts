import assert from "node:assert/strict";
import test from "node:test";
import {
  buildToolResultRefinementPrompt,
  runAgentToolLoop,
  summarizeToolResultsForMetadata,
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
