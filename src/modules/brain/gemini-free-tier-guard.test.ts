import assert from "node:assert/strict";
import test from "node:test";
import { buildGeminiFreePublicOperationFrame } from "./gemini-free-tier-guard.js";

test("Gemini free public frame allows public Turkish news requests", () => {
  assert.equal(
    buildGeminiFreePublicOperationFrame("Türkiye'nin ekonomisi hakkındaki haberler"),
    "Türkiye'nin ekonomisi hakkındaki haberler",
  );
});

test("Gemini free public frame blocks private Turkish account requests", () => {
  assert.equal(buildGeminiFreePublicOperationFrame("Son 3 mailim nedir"), null);
  assert.equal(
    buildGeminiFreePublicOperationFrame("Bağlı hesabımdaki son mailleri göster"),
    null,
  );
});
