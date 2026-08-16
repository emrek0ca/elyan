import test from "node:test";
import assert from "node:assert/strict";
import {
  getDesktopCapabilityOntology,
  matchDesktopCapabilitiesSemantically,
  normalizeText,
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

// Bu sözcüksel katman ADAY ÜRETİR; top-1 kesinliği artık onun işi değil.
//
// Ölçüm (routing-eval) bunu sayıyla gösterdi: karakter n-gramı + IDF, hiç
// görülmemiş ifadelerde %48.8'de kalıyor çünkü eşanlamlıyı köprüleyemiyor —
// "gir" token'ı hem "siteye gir" hem "forma metni gir" içinde geçer, aradaki
// niyet farkını sözcük göremez. Top-1 kesinliği, gerçek anlamsal katmanın
// (desktop-capability-embedding-match, e5) işi; o katman ölçümde aynı kümede
// %73.2 veriyor ve embedder yoksa buraya düşülüyor.
//
// Dolayısıyla buradaki sözleşme şudur: doğru yetenek ADAY PENCERESİNDEN
// düşmemeli. Top-1 iddiası routing-eval korpusunda tutuluyor.
test("desktop capability lexical matcher keeps browser work inside the candidate window", () => {
  for (const query of [
    "Chrome'da şunu aç",
    "tarayıcıdan bak",
    "siteye gir",
    "bunu webde bul",
  ]) {
    const matches = matchDesktopCapabilitiesSemantically({
      query,
      intent: "browser_workflow",
      sideEffectLevel: "none",
      limit: 3,
    });
    const candidates = matches.map((match) => match.capability);
    assert.ok(
      candidates.some((capability) => capability.startsWith("browser")),
      `${query} → ${candidates.join(", ")}`,
    );
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

test("capability matching keeps incompatible side-effect tools out of top-1", () => {
  assert.equal(normalizeText("çalıştırı kapat"), "calistiri kapat");

  const cases = [
    ["terminal oturumunu kapat", "close_app"],
    ["makineyi tamamen kapatabilir misin", "close_app"],
    ["ekibe bir yazı gönder ama önce göreyim", "email_send"],
    ["abime bi selam yolla whatsapptan", "email_send"],
    ["elektronik tablo programları arasındaki fark ne", "spreadsheet_write"],
  ] as const;

  for (const [query, forbidden] of cases) {
    const [match] = matchDesktopCapabilitiesSemantically({
      query,
      limit: 1,
      threshold: 0,
    });
    assert.notEqual(
      match?.capability,
      forbidden,
      `${query} → ${match?.capability ?? "(yok)"}`,
    );
  }
});
