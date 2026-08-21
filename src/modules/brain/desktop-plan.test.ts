import assert from "node:assert/strict";
import test from "node:test";
import { extractFirstJsonObject } from "./desktop-plan.js";

test("extractFirstJsonObject prefers the compiled plan after model reasoning", () => {
  const output = [
    '<think>{"draft":"not a plan"}</think>',
    '{"contract":"elyan.plan.v2","steps":[{"id":"close","capability":"close_app","args":{"app_name":"Chrome"}}]}',
  ].join("\n");

  assert.deepEqual(extractFirstJsonObject(output), {
    contract: "elyan.plan.v2",
    steps: [
      {
        id: "close",
        capability: "close_app",
        args: { app_name: "Chrome" },
      },
    ],
  });
});

test("extractFirstJsonObject keeps backward-compatible first-object fallback", () => {
  assert.deepEqual(extractFirstJsonObject('prefix {"ok":true} suffix'), {
    ok: true,
  });
  assert.equal(extractFirstJsonObject("no json"), null);
});
