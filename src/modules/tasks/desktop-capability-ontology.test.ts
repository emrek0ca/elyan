import test from "node:test";
import assert from "node:assert/strict";
import {
  getDesktopCapabilityOntology,
  matchDesktopCapabilitiesSemantically,
} from "./desktop-capability-ontology.js";

test("desktop capability ontology exposes stable metadata for every manifest entry", () => {
  const ontology = getDesktopCapabilityOntology();
  assert.ok(ontology.length > 0);
  const browser = ontology.find((entry) => entry.canonicalId === "browser_control");
  assert.ok(browser);
  assert.equal(browser.privacyClass, "permission_gated");
  assert.equal(browser.requiresApproval, true);
  assert.equal(browser.runtimeNames.includes("browser_control"), true);
  assert.ok(browser.aliases.length > 0);
  assert.ok(browser.examples.length > 0);
  assert.ok(browser.negativeExamples.length > 0);
});

test("desktop capability semantic matcher maps Turkish browser phrasing to browser_control", () => {
  for (const query of [
    "Chrome'da şunu aç",
    "tarayıcıdan bak",
    "siteye gir",
    "bunu webde bul",
  ]) {
    const [match] = matchDesktopCapabilitiesSemantically({
      query,
      intent: "browser_workflow",
      sideEffectLevel: "none",
      limit: 1,
    });
    assert.equal(match?.capability, "browser_control", query);
  }
});

test("desktop capability semantic matcher separates document artifact work from browser opening", () => {
  const [match] = matchDesktopCapabilitiesSemantically({
    query: "masaüstüne pdf rapor hazırla ve kaydet",
    intent: "document_workflow",
    sideEffectLevel: "write",
    limit: 1,
  });

  assert.equal(match?.capability, "document_write");
});
