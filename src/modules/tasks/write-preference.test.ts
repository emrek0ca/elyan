import assert from "node:assert/strict";
import test from "node:test";
import { parsePreferredWriteRoot } from "./write-preference.js";

test("tercih izinli kökün ALTINI işaret edebilir", () => {
  assert.equal(parsePreferredWriteRoot("~/Desktop/Raporlar"), "~/Desktop/Raporlar");
  assert.equal(parsePreferredWriteRoot("~/Documents/İş/2026"), "~/Documents/İş/2026");
  assert.equal(parsePreferredWriteRoot("workspace"), "workspace");
  assert.equal(parsePreferredWriteRoot("~/Desktop/"), "~/Desktop");
});

test("TERCİH YENİ ÜST KÖK AÇAMAZ", () => {
  // Bir hafıza kaydı — modelin çıkardığı bir cümleden doğabilir — sessizce
  // yeni bir yazma yetkisi üretmemeli.
  assert.equal(parsePreferredWriteRoot("/etc"), null);
  assert.equal(parsePreferredWriteRoot("~/Library/Keychains"), null);
  assert.equal(parsePreferredWriteRoot("/"), null);
  assert.equal(parsePreferredWriteRoot("~/"), null);
  assert.equal(parsePreferredWriteRoot("C:/Windows"), null);
});

test("yol kaçışı reddedilir", () => {
  assert.equal(parsePreferredWriteRoot("~/Desktop/../../etc"), null);
  assert.equal(parsePreferredWriteRoot("~/Desktop/.."), null);
  assert.equal(parsePreferredWriteRoot("workspace/../secrets"), null);
});

test("aşırı derin veya bozuk yol reddedilir", () => {
  assert.equal(parsePreferredWriteRoot("~/Desktop/a/b/c"), null);
  assert.equal(parsePreferredWriteRoot("~/Desktop/" + "x".repeat(80)), null);
  assert.equal(parsePreferredWriteRoot(""), null);
  assert.equal(parsePreferredWriteRoot(null), null);
  assert.equal(parsePreferredWriteRoot("~/Desktop/a\nb"), null);
});

test("ters bölü normalleştirilir", () => {
  assert.equal(parsePreferredWriteRoot("~\\Desktop\\Raporlar"), "~/Desktop/Raporlar");
});
