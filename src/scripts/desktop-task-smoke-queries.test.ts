import assert from "node:assert/strict";
import test from "node:test";
import { latestDesktopTaskIdQuery } from "./desktop-task-smoke-queries.js";

test("desktop watch query excludes server-brain tasks", () => {
  const query = latestDesktopTaskIdQuery();

  assert.match(query, /where payload->'metadata'->'routeDecision'->'taskRoute'/);
  assert.match(query, /'operationalRoute' = 'desktop_runtime'/);
  assert.match(query, /order by created_at desc limit 1/);
});
