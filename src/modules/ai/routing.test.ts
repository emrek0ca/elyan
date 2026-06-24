import assert from "node:assert/strict";
import test from "node:test";
import { resolveAiRoute } from "./routing.js";

test("resolveAiRoute defaults to Groq", () => {
  const route = resolveAiRoute({
    workload: "fast_route",
  });

  assert.equal(route.provider, "groq");
  assert.equal(route.model, "openai/gpt-oss-20b");
  assert.deepEqual(route.fallbacks, ["qwen/qwen3.6-27b"]);
});
