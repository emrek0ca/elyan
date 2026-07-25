import assert from "node:assert/strict";
import test from "node:test";
import {
  ensureUserFacingMessage,
  isCapabilityLabelOnly,
} from "./capability-label-guard.js";

// Kullanıcının canlıda gördüğü üç sızıntı — hiçbiri cevap olarak gitmemeli.
test("labels seen in production are never delivered", () => {
  for (const leak of [
    "Klasör ağacı",
    "Belge okuma",
    "desktop_operator.run",
    "directory_tree",
    "Terminal komutu",
  ]) {
    assert.ok(isCapabilityLabelOnly(leak), `etiket yakalanmadı: ${leak}`);
    assert.equal(ensureUserFacingMessage(leak), "İşlem tamamlandı.");
  }
});

test("real tool output is delivered untouched", () => {
  for (const real of [
    "Dosya oluşturuldu: alışverişlistesi.txt",
    "Klasör ağacı çıkarıldı: 12 dosya, 3 klasör",
    "Belge okuma tamamlandı, 3 sayfa özetlendi",
    "Pil %76, şarj oluyor",
    "open_app:spotify",
  ]) {
    assert.equal(ensureUserFacingMessage(real), real, `gerçek çıktı kesildi: ${real}`);
  }
});

test("multi-label summaries are caught too", () => {
  assert.ok(isCapabilityLabelOnly("Belge okuma; Klasör ağacı"));
  assert.ok(isCapabilityLabelOnly("directory_tree, document_read"));
});

test("empty and long text are left alone", () => {
  assert.equal(ensureUserFacingMessage(""), "");
  const long = "Klasör ağacı ".repeat(20);
  assert.equal(ensureUserFacingMessage(long), long);
});
