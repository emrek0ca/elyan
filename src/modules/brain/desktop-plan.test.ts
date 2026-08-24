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

test("extractFirstJsonObject selects the final plan when reasoning contains a draft plan", () => {
  const output = [
    '<think>{"contract":"elyan.plan.v2","steps":[{"id":"draft","capability":"shell_run","args":{}}]}</think>',
    '{"steps":[{"id":"final","capability":"directory_tree","args":{"path":"~/Desktop"}}]}',
  ].join("\n");

  assert.deepEqual(extractFirstJsonObject(output), {
    steps: [
      {
        id: "final",
        capability: "directory_tree",
        args: { path: "~/Desktop" },
      },
    ],
  });
});
