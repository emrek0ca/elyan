import assert from "node:assert/strict";
import test from "node:test";
import { capabilityUtteranceCount } from "./desktop-capability-embedding-match.js";
import { getDesktopCapabilityOntology } from "./desktop-capability-ontology.js";

// ---------------------------------------------------------------------------
// YENİ ARAÇ EKLENDİĞİNDE HİSSEDİLMELİ.
//
// CANLI ÖLÇÜM (2026-08-23): `file_find` yeteneği eklendi, masaüstü onu beyan
// etti, manifest ve ontolojiye girdi — ama eşleştirmede HİÇ SEÇİLMEDİ; kendi
// kullanım örnekleriyle bile 0/4. Sebep: eşleştirici yalnız
// `manifest.utterances` okuyordu ve yeni yeteneğin utterances'ı boştu
// (yazarı `whenToUse` doldurmuştu). Anlamsal varlığı SIFIRDI.
//
// Yani bir araç eklemek onu seçilebilir yapmıyordu. Bu test o sessiz boşluğu
// kapatır: örnek cümlesi olmayan yetenek pratikte seçilemez, çünkü yalnız
// kimlik metniyle yarışır ve örneği olan her rakibe kaybeder.
//
// Düzeltme sonrası ölçüm: 2/7 → 7/7.
// ---------------------------------------------------------------------------

const MIN_PHRASES = 3;

test("her yeteneğin kullanıcı dilinde örneği var", () => {
  const ontology = getDesktopCapabilityOntology();
  const starved = ontology
    .filter((entry) => capabilityUtteranceCount(entry) < MIN_PHRASES)
    .map((entry) => `${entry.canonicalId} (${capabilityUtteranceCount(entry)} örnek)`);

  assert.deepEqual(
    starved,
    [],
    `bu yetenekler pratikte seçilemez — phrasebook ya da whenToUse'a örnek ekle:\n  ${starved.join("\n  ")}`,
  );
});

test("yeni eklenen yetenek de bu kurala tabi", () => {
  const fileFind = getDesktopCapabilityOntology().find(
    (entry) => entry.canonicalId === "file_find",
  );
  assert.ok(fileFind, "file_find ontolojide yok");
  assert.ok(
    capabilityUtteranceCount(fileFind) >= MIN_PHRASES,
    "file_find yeterli örnek taşımıyor",
  );
});
