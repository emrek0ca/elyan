import assert from "node:assert/strict";
import test from "node:test";
import {
  ensureUserFacingMessage,
  isCapabilityLabelOnly,
} from "./capability-label-guard.js";

test("capability labels are never delivered as an answer", () => {
  // Canlıda kullanıcının sırayla gördüğü üç sızıntı.
  for (const leak of ["Klasör ağacı", "Belge okuma", "desktop_operator.run"]) {
    assert.ok(isCapabilityLabelOnly(leak), `${leak} etiket sayılmadı`);
    assert.equal(ensureUserFacingMessage(leak), "İşlem tamamlandı.");
  }
});

test("multiple labels joined are still labels", () => {
  assert.ok(isCapabilityLabelOnly("Belge okuma, Klasör ağacı"));
});

test("real tool output is delivered untouched", () => {
  const real = [
    "Klasör ağacı çıkarıldı: 12 dosya bulundu.",
    "DOCX oluşturuldu: rapor.docx",
    "Masaüstünde 3 klasör ve 8 dosya var.",
    "Pil %76, şarj oluyor.",
  ];
  for (const text of real) {
    assert.ok(!isCapabilityLabelOnly(text), `${text} yanlışlıkla etiket sayıldı`);
    assert.equal(ensureUserFacingMessage(text), text);
  }
});

test("empty and long text are left alone", () => {
  assert.equal(ensureUserFacingMessage(""), "");
  const long = "a".repeat(400);
  assert.equal(ensureUserFacingMessage(long), long);
});
