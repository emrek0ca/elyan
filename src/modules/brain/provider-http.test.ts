import assert from "node:assert/strict";
import test from "node:test";
import { joinProviderUrl } from "./provider-http.js";

test("joinProviderUrl normalizes duplicate v1 path segments", () => {
  assert.equal(
    joinProviderUrl("https://api.example.com/v1/", "/v1/chat/completions"),
    "https://api.example.com/v1/chat/completions",
  );
});

test("joinProviderUrl accepts paths with or without a leading slash", () => {
  assert.equal(
    joinProviderUrl("http://127.0.0.1:11434", "api/chat"),
    "http://127.0.0.1:11434/api/chat",
  );
});
