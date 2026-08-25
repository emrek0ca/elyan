import assert from "node:assert/strict";
import test from "node:test";
import {
  evaluateTemplateCandidate,
  synthesizeCompiledTemplates,
  TEMPLATE_MIN_EPISODES,
} from "./template-synthesis.js";
import type { EpisodeDigestGroup } from "./episode-store.js";

function group(overrides: Partial<EpisodeDigestGroup> = {}): EpisodeDigestGroup {
  return {
    intentFamily: "desktop_research_save",
    contractDigest: "digest-1",
    totalCount: 24,
    fulfilledCount: 24,
    stepShapes: [
      { capability: "web_research", device: null, argKeys: ["query"] },
      { capability: "document_write", device: "desktop", argKeys: ["path", "content"] },
    ],
    evidenceKinds: ["artifact"],
    medianLatencyMs: 4200,
    ...overrides,
  };
}

test("doğrulanmış ve tutarlı tekrar şablona dönüşür", () => {
  const result = evaluateTemplateCandidate(group());
  assert.ok("candidate" in result);
  if (!("candidate" in result)) return;
  assert.equal(result.candidate.intentFamily, "desktop_research_save");
  assert.equal(result.candidate.steps.length, 2);
  assert.deepEqual(
    result.candidate.steps.map((step) => step.effect),
    ["read", "write"],
  );
  assert.deepEqual(result.candidate.steps[1].argSlots, ["path", "content"]);
});

test("tekrar yetmiyorsa şablon olmaz", () => {
  const result = evaluateTemplateCandidate(
    group({ totalCount: TEMPLATE_MIN_EPISODES - 1, fulfilledCount: TEMPLATE_MIN_EPISODES - 1 }),
  );
  assert.ok("rejection" in result);
  if ("rejection" in result) {
    assert.equal(result.rejection.reason, "insufficient_episodes");
  }
});

test("tek bir başarısız epizot bile şablonu düşürür", () => {
  const result = evaluateTemplateCandidate(group({ totalCount: 24, fulfilledCount: 23 }));
  assert.ok("rejection" in result);
  if ("rejection" in result) {
    assert.equal(result.rejection.reason, "not_all_fulfilled");
  }
});

test("KANITSIZ tekrar şablon olmaz — aynı yanlış iş 20 kez yapılmış olabilir", () => {
  const result = evaluateTemplateCandidate(group({ evidenceKinds: [] }));
  assert.ok("rejection" in result);
  if ("rejection" in result) {
    assert.equal(result.rejection.reason, "no_verification_evidence");
  }
});

test("generic yürütücü içeren dizi şablona giremez", () => {
  const result = evaluateTemplateCandidate(
    group({
      stepShapes: [
        { capability: "desktop_operator.run", device: "desktop", argKeys: ["instruction"] },
      ],
    }),
  );
  assert.ok("rejection" in result);
  if ("rejection" in result) {
    assert.equal(result.rejection.reason, "generic_executor_step");
  }
});

test("ayrı onay gerektiren capability şablona giremez", () => {
  const result = evaluateTemplateCandidate(
    group({
      stepShapes: [{ capability: "email_send", device: null, argKeys: ["to"] }],
    }),
  );
  assert.ok("rejection" in result);
  if ("rejection" in result) {
    assert.equal(result.rejection.reason, "separate_approval_capability");
  }
});

test("riskli slot adı şablonu düşürür", () => {
  const result = evaluateTemplateCandidate(
    group({
      stepShapes: [
        { capability: "web_research", device: null, argKeys: ["query"] },
        { capability: "document_write", device: "desktop", argKeys: ["path", "api_key"] },
      ],
    }),
  );
  assert.ok("rejection" in result);
  if ("rejection" in result) {
    assert.equal(result.rejection.reason, "elevated_risk_arguments");
  }
});

test("tanınmayan capability şablona giremez", () => {
  const result = evaluateTemplateCandidate(
    group({ stepShapes: [{ capability: "made_up_tool", device: null, argKeys: [] }] }),
  );
  assert.ok("rejection" in result);
  if ("rejection" in result) {
    assert.equal(result.rejection.reason, "unknown_capability");
  }
});

test("aile içinde iki imza bölüşüyorsa hiçbiri kanonik yol sayılmaz", () => {
  const { candidates, rejected } = synthesizeCompiledTemplates([
    group({ contractDigest: "a", totalCount: 24, fulfilledCount: 24 }),
    group({ contractDigest: "b", totalCount: 22, fulfilledCount: 22 }),
  ]);
  assert.equal(candidates.length, 0);
  assert.equal(rejected.length, 2);
  assert.equal(rejected[0].reason, "inconsistent_step_sequence");
});

test("ailede baskın imza aday olur", () => {
  const { candidates } = synthesizeCompiledTemplates([
    group({ contractDigest: "a", totalCount: 40, fulfilledCount: 40 }),
    group({ contractDigest: "b", totalCount: 2, fulfilledCount: 2 }),
  ]);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].contractDigest, "a");
  assert.ok(candidates[0].consistency >= 0.9);
});
