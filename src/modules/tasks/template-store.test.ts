import assert from "node:assert/strict";
import test from "node:test";
import {
  decideTemplateLifecycle,
  TEMPLATE_SHADOW_MIN_MATCHES,
  type StoredCompiledTemplate,
} from "./template-store.js";

function template(
  overrides: Partial<StoredCompiledTemplate> = {},
): StoredCompiledTemplate {
  return {
    templateId: "t1",
    intentFamily: "desktop_research_save",
    contractDigest: "d1",
    steps: [],
    state: "candidate",
    supportingEpisodes: 24,
    consistency: 0.98,
    shadowMatches: 0,
    shadowAgreements: 0,
    wrongExecutionCount: 0,
    ...overrides,
  };
}

test("aday önce GÖLGEYE geçer, doğrudan yayına değil", () => {
  assert.deepEqual(decideTemplateLifecycle(template()), {
    action: "advance",
    to: "shadow",
  });
});

test("gölge eşleşmesi yetmeden kanaryaya geçilmez", () => {
  const decision = decideTemplateLifecycle(
    template({ state: "shadow", shadowMatches: 5, shadowAgreements: 5 }),
  );
  assert.deepEqual(decision, {
    action: "hold",
    reason: "insufficient_shadow_matches",
  });
});

test("gölgede anlaşma yüksekse kanaryaya geçer", () => {
  const decision = decideTemplateLifecycle(
    template({
      state: "shadow",
      shadowMatches: TEMPLATE_SHADOW_MIN_MATCHES,
      shadowAgreements: TEMPLATE_SHADOW_MIN_MATCHES,
    }),
  );
  assert.deepEqual(decision, { action: "advance", to: "canary" });
});

test("gölgede anlaşmazlık şablonu emekli eder", () => {
  const decision = decideTemplateLifecycle(
    template({
      state: "shadow",
      shadowMatches: TEMPLATE_SHADOW_MIN_MATCHES,
      shadowAgreements: 10,
    }),
  );
  assert.deepEqual(decision, { action: "retire", reason: "shadow_disagreement" });
});

test("TEK bir yanlış yürütme eşiğe bakılmadan emekli eder", () => {
  const decision = decideTemplateLifecycle(
    template({
      state: "canary",
      shadowMatches: 100,
      shadowAgreements: 100,
      wrongExecutionCount: 1,
    }),
  );
  assert.deepEqual(decision, { action: "retire", reason: "wrong_execution_observed" });
});

test("kanaryadan yayına geçiş OTOMATİK değildir", () => {
  const decision = decideTemplateLifecycle(
    template({ state: "canary", shadowMatches: 500, shadowAgreements: 500 }),
  );
  assert.deepEqual(decision, { action: "hold", reason: "manual_release_required" });
});
