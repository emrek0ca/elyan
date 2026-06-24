import assert from "node:assert/strict";
import test from "node:test";

import { buildAppleCallbackLandingHtml, normalizeAppleCallbackPayload } from "./routes.js";

test("normalizeAppleCallbackPayload reads apple web callback fields from body and query", () => {
  const normalized = normalizeAppleCallbackPayload(
    {
      id_token: "body-id-token",
      code: "body-code",
      user: '{"name":{"firstName":"Emre"}}',
    },
    {
      state: "query-state",
      display_name: "Emre Koca",
      email: "emre@example.com",
    },
  );

  assert.equal(normalized.idToken, "body-id-token");
  assert.equal(normalized.authorizationCode, "body-code");
  assert.equal(normalized.state, "query-state");
  assert.equal(normalized.user, '{"name":{"firstName":"Emre"}}');
  assert.equal(normalized.displayName, "Emre Koca");
  assert.equal(normalized.email, "emre@example.com");
});

test("buildAppleCallbackLandingHtml does not leak apple callback secrets", () => {
  const html = buildAppleCallbackLandingHtml();

  assert.match(html, /Giriş tamamlandı/);
  assert.doesNotMatch(html, /id_token|authorizationCode|code=/i);
});
