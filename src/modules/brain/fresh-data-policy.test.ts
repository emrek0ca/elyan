import assert from "node:assert/strict";
import test from "node:test";
import {
  buildFreshDataEnvelope,
  classifyFreshDataDomain,
  normalizeFreshDataEnvelope,
  resolveFreshDataPolicy,
  sourceFreshnessStatus,
  sourceTrustScore,
} from "./fresh-data-policy.js";

test("classifyFreshDataDomain separates volatile data domains deterministically", () => {
  assert.equal(classifyFreshDataDomain("Bugünkü haberler").domain, "news");
  assert.equal(classifyFreshDataDomain("Güncel gram altın fiyatı").domain, "market");
  assert.equal(classifyFreshDataDomain("İstanbul hava durumu").domain, "weather");
  assert.equal(classifyFreshDataDomain("Maç sonucu kaç kaç?").domain, "sports");
  assert.equal(classifyFreshDataDomain("CVE-2026-1234 etkileniyor mu?").domain, "software_security");
  assert.equal(classifyFreshDataDomain("Bu URL'yi incele: https://example.com").domain, "url_review");
});

test("resolveFreshDataPolicy uses short TTL and no stale fallback for live market data", () => {
  const policy = resolveFreshDataPolicy("Bugünkü dolar kaç TL?");
  assert.equal(policy.domain, "market");
  assert.equal(policy.freshnessRequired, true);
  assert.equal(policy.cacheTtlMs, 30_000);
  assert.equal(policy.allowStaleIfError, false);
  assert.equal(policy.minimumSources, 2);
  assert.equal(policy.minimumVerifiedSources, 2);
});

test("resolveFreshDataPolicy separates current personal chat from current public facts", () => {
  assert.equal(
    resolveFreshDataPolicy("Bugün nasılsın?", {
      socialTurn: true,
      publicKnowledgeRequest: false,
    }).freshnessRequired,
    false,
  );
  assert.equal(
    resolveFreshDataPolicy("Bugün Türkiye'de ne oldu?", {
      socialTurn: false,
      publicKnowledgeRequest: false,
    }).freshnessRequired,
    true,
  );
});

test("sourceTrustScore prefers domain authorities without exceeding one", () => {
  const policy = resolveFreshDataPolicy("Güncel dolar kuru");
  assert.equal(
    sourceTrustScore({
      host: "www.tcmb.gov.tr",
      authority: "official",
      policy,
    }),
    1,
  );
  assert.ok(
    sourceTrustScore({
      host: "example.com",
      authority: "standard",
      policy,
    }) < 0.7,
  );
});

test("fresh data envelope requires independent hosts and verified evidence", () => {
  const policy = resolveFreshDataPolicy("Güncel altın fiyatı");
  const envelope = buildFreshDataEnvelope({
    policy,
    requestedAt: new Date("2026-07-09T12:00:10.000Z"),
    retrievedAt: "2026-07-09T12:00:00.000Z",
    cacheState: "miss",
    sourceCount: 2,
    verifiedSourceCount: 1,
    datedSourceCount: 1,
    independentHostCount: 1,
  });
  assert.equal(envelope.status, "fresh");
  assert.equal(envelope.evidence.sufficient, false);
});

test("fresh data envelope requires enough non-stale sources for current claims", () => {
  const policy = resolveFreshDataPolicy("Bugünkü haberler");
  const envelope = buildFreshDataEnvelope({
    policy,
    requestedAt: new Date("2026-07-09T12:00:00.000Z"),
    retrievedAt: "2026-07-09T12:00:00.000Z",
    cacheState: "miss",
    sourceCount: 2,
    freshSourceCount: 1,
    verifiedSourceCount: 2,
    freshVerifiedSourceCount: 1,
    datedSourceCount: 2,
    freshDatedSourceCount: 1,
    independentHostCount: 2,
  });
  assert.equal(envelope.status, "fresh");
  assert.equal(envelope.evidence.sufficient, false);
});

test("fresh data envelope does not count stale verified sources as current evidence", () => {
  const policy = resolveFreshDataPolicy("Bugünkü haberler");
  const envelope = buildFreshDataEnvelope({
    policy,
    requestedAt: new Date("2026-07-09T12:00:00.000Z"),
    retrievedAt: "2026-07-09T12:00:00.000Z",
    cacheState: "miss",
    sourceCount: 2,
    freshSourceCount: 2,
    verifiedSourceCount: 1,
    freshVerifiedSourceCount: 0,
    datedSourceCount: 2,
    freshDatedSourceCount: 2,
    independentHostCount: 2,
  });
  assert.equal(envelope.status, "fresh");
  assert.equal(envelope.evidence.sufficient, false);
});

test("news publication age is separate from the short response cache TTL", () => {
  const policy = resolveFreshDataPolicy("Bugünkü haberler");
  const now = new Date("2026-07-09T12:00:00.000Z");
  assert.equal(
    sourceFreshnessStatus({
      policy,
      now,
      publishedAt: "2026-07-09T11:30:00.000Z",
      observedAt: now.toISOString(),
    }),
    "fresh",
  );
  assert.equal(
    sourceFreshnessStatus({
      policy,
      now,
      publishedAt: "2026-07-06T11:30:00.000Z",
      observedAt: now.toISOString(),
    }),
    "stale",
  );
});

test("news evidence can be sufficient from fresh independent sources even when page dates are missing", () => {
  const policy = resolveFreshDataPolicy("Bugünkü haberler");
  const envelope = buildFreshDataEnvelope({
    policy,
    requestedAt: new Date("2026-07-09T12:00:00.000Z"),
    retrievedAt: "2026-07-09T12:00:00.000Z",
    cacheState: "miss",
    sourceCount: 2,
    verifiedSourceCount: 1,
    datedSourceCount: 0,
    independentHostCount: 2,
  });
  assert.equal(envelope.evidence.sufficient, true);
});

test("normalizeFreshDataEnvelope validates and trims persisted JSON envelopes", () => {
  const envelope = buildFreshDataEnvelope({
    policy: resolveFreshDataPolicy("Bugünkü haberler"),
    requestedAt: new Date("2026-07-09T12:00:00.000Z"),
    retrievedAt: "2026-07-09T12:00:00.000Z",
    cacheState: "miss",
    sourceCount: 2,
    verifiedSourceCount: 1,
    datedSourceCount: 1,
    independentHostCount: 2,
    reasons: ["x".repeat(200), "fresh"],
  });

  const normalized = normalizeFreshDataEnvelope({
    ...envelope,
    extraInternalField: "drop-me",
    reasons: [...envelope.reasons, "x".repeat(200)],
  });

  assert.equal(normalized?.schemaVersion, "elyan.fresh_data.v1");
  assert.equal((normalized as Record<string, unknown>).extraInternalField, undefined);
  const lastReason = normalized?.reasons[(normalized?.reasons.length ?? 1) - 1] ?? "";
  assert.ok(lastReason.length <= 80);
  assert.equal(normalizeFreshDataEnvelope({ ...envelope, domain: "bad" }), null);
});
