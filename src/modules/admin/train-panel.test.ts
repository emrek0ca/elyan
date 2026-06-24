import assert from "node:assert/strict";
import test from "node:test";
import Fastify from "fastify";
import { trainPanelRoutes } from "./train-panel.js";

test("train panel serves html and assets", async () => {
  const app = Fastify();
  await app.register(trainPanelRoutes);

  const indexResponse = await app.inject({
    method: "GET",
    url: "/train",
  });

  assert.equal(indexResponse.statusCode, 200);
  assert.match(indexResponse.headers["content-type"] ?? "", /text\/html/);
  assert.match(indexResponse.body, /Elyan Train/);
  assert.doesNotMatch(indexResponse.body, /favicon\.ico/);

  const scriptResponse = await app.inject({
    method: "GET",
    url: "/train/app.js",
  });

  assert.equal(scriptResponse.statusCode, 200);
  assert.match(scriptResponse.headers["content-type"] ?? "", /javascript/);
  assert.match(scriptResponse.body, /resolveDefaultBackendUrl/);

  await app.close();
});
