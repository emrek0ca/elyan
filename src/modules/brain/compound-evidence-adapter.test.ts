import assert from "node:assert/strict";
import test from "node:test";
import { compoundEvidenceToWebGrounding } from "./compound-evidence-adapter.js";
import { buildUnavailableWebGroundingResult } from "./web-grounding.js";

test("Compound citations become one canonical web grounding result", () => {
  const existing = buildUnavailableWebGroundingResult({
    enabled: true,
    prompt: "güncel altın fiyatı",
    degradedReason: "compound_evidence_pending",
  });
  const result = compoundEvidenceToWebGrounding({
    prompt: "güncel altın fiyatı",
    existing,
    retrievedAt: "2026-08-29T12:00:00.000Z",
    evidence: {
      toolsUsed: ["web_search", "visit_website"],
      searchQueries: ["gold spot price official"],
      citations: [
        {
          title: "Alpha Vantage Gold",
          url: "https://www.alphavantage.co/gold",
          snippet: "Altın 3410.25 USD/ons",
          observedAt: "2026-08-29T11:59:55.000Z",
          toolType: "visit_website",
        },
        {
          title: "Gold",
          url: "https://example.com/gold",
          snippet: "Altın fiyatı 3410.25 USD/ons",
          observedAt: "2026-08-29T11:59:56.000Z",
          toolType: "visit_website",
        },
      ],
    },
  });

  assert.ok(result);
  assert.equal(result.source, "groq_compound");
  assert.equal(result.used, true);
  assert.equal(result.results.length, 2);
  assert.equal(result.results[0]?.verificationState, "verified");
  assert.equal(result.freshData.evidence.sufficient, true);
});

test("undated market citations remain insufficient", () => {
  const existing = buildUnavailableWebGroundingResult({
    enabled: true,
    prompt: "güncel altın fiyatı",
    degradedReason: "compound_evidence_pending",
  });
  const result = compoundEvidenceToWebGrounding({
    prompt: "güncel altın fiyatı",
    existing,
    retrievedAt: "2026-08-29T12:00:00.000Z",
    evidence: {
      toolsUsed: ["web_search"],
      searchQueries: ["gold price"],
      citations: [
        {
          title: "Gold",
          url: "https://example.com/gold",
          snippet: "Gold price",
          toolType: "web_search",
        },
      ],
    },
  });

  assert.ok(result);
  assert.equal(result.used, false);
  assert.equal(result.freshData.evidence.datedSourceCount, 0);
});
