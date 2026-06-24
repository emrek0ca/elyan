import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { buildWeakEtag, sendConditionalJson } from "./http.js";

test("buildWeakEtag is stable for identical payloads", () => {
  const payload = { id: "session-1", title: "Elyan" };
  assert.equal(buildWeakEtag(payload), buildWeakEtag(payload));
});

test("sendConditionalJson returns 304 when If-None-Match matches", async () => {
  const app = Fastify();

  app.get("/etag", async (request, reply) => {
    return sendConditionalJson(request, reply, {
      id: "session-1",
      title: "Elyan",
    });
  });

  const first = await app.inject({
    method: "GET",
    url: "/etag",
  });

  assert.equal(first.statusCode, 200);
  assert.equal(first.headers["cache-control"], "private, max-age=0, must-revalidate");
  assert.match(String(first.headers.etag ?? ""), /^W\//);

  const second = await app.inject({
    method: "GET",
    url: "/etag",
    headers: {
      "if-none-match": String(first.headers.etag),
    },
  });

  assert.equal(second.statusCode, 304);
  assert.equal(second.body, "");

  await app.close();
});
