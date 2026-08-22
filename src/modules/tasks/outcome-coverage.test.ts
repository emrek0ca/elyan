import assert from "node:assert/strict";
import test from "node:test";
import { validateOutcomeCoverage } from "./plan-validators.js";

// ---------------------------------------------------------------------------
// SONUÇ KAPSAMI — bileşik isteklerin tek adıma çökmesi genel bir eksikti.
//
// Canlı arıza (2026-08-22, görev 3834eb15) "Ekran görüntüsü al ve masaüstüne
// kaydet": iş emri `{"kind":"file_update","required":true}` BEYAN ETMİŞTİ —
// sistem dosya çıktısı gerektiğini biliyordu. Plan ise tek adımdı:
// `desktop_operator.observe_screen`, ki hiçbir dosya üretmez.
//
// Aynı sınıf "Safariden youtube u aç" turunda da görülmüştü (uygulama açıldı,
// adrese hiç gidilmedi). Bu yüzden düzeltme göreve özel değil MEKANİK: iş
// emrinin kendi beyanı, manifestin kendi beyanıyla karşılaştırılır.
// ---------------------------------------------------------------------------

const requiresFile = [
  { kind: "chat_result", required: true },
  { kind: "file_update", required: true },
];

function step(capability: string) {
  return { id: "s1", capability, args: {}, dependsOn: [] } as never;
}

test("an observe-only plan cannot satisfy a required file outcome", () => {
  const issues = validateOutcomeCoverage(
    [step("desktop_operator.observe_screen")],
    requiresFile,
  );
  assert.equal(issues.length, 1);
  // Hata metni replan'a NE eksik olduğunu ve hangi yeteneklerin üretebileceğini
  // söylemeli — reddetmek tek başına yetmez.
  assert.match(issues[0], /saved file\/artifact/);
  assert.match(issues[0], /for example:/);
});

test("a plan containing a writer step satisfies it", () => {
  // `make_directory` hiçbir ARTEFAKT üretmez ama "klasör oluştur" isteğini tam
  // olarak karşılar; yalnız artefakt üreticilerini saymak DOĞRU planları
  // reddederdi (kendi kapımın yanlış-pozitifi, 2026-08-22).
  for (const writer of ["document_write", "file_write", "image_generate", "make_directory", "file_move"]) {
    const issues = validateOutcomeCoverage(
      [step("desktop_operator.observe_screen"), step(writer)],
      requiresFile,
    );
    assert.deepEqual(issues, [], `${writer} kapsamı sağlamalı`);
  }
});

test("requests without a required persistent outcome are never blocked", () => {
  // "Chrome u aç" gibi turlar: yalnız chat_result + isteğe bağlı browser_state.
  const issues = validateOutcomeCoverage([step("open_app")], [
    { kind: "chat_result", required: true },
    { kind: "browser_state", required: false },
  ]);
  assert.deepEqual(issues, []);
});

test("an optional artifact outcome does not force a writer step", () => {
  const issues = validateOutcomeCoverage([step("close_app")], [
    { kind: "chat_result", required: true },
    { kind: "artifact", required: false },
  ]);
  assert.deepEqual(issues, []);
});

test("missing or empty declarations never produce noise", () => {
  assert.deepEqual(validateOutcomeCoverage([step("open_app")], undefined), []);
  assert.deepEqual(validateOutcomeCoverage([step("open_app")], []), []);
});
