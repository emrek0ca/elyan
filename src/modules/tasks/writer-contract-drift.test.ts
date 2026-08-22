import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  PROSE_WRITER_CAPABILITIES,
  WRITER_PROSE_WORKLOAD,
  WRITER_RESEARCH_WORKLOAD,
  requestedOutputFormat,
} from "./writer-content.js";
import { decideStructuredResponseDecision } from "../../core/understanding/structured-output-policy.js";
import { SHARED_BRAIN_WORKLOAD_PROFILES } from "../brain/workloads.js";

// ---------------------------------------------------------------------------
// SÖZLEŞME KAYMASI KAPILARI.
//
// Bu gecenin baskın hata sınıfı: aynı şeyi İKİ yer anlatıyor ve ayrışıyorlar.
// Yakalananlar — yetenek kaydı vs spec, plan zarfı anahtarı, iş yükü şeridi vs
// düz metin ihtiyacı, biçim bilgisinin plandan runtime'a geçmemesi.
// İlk ikisi zaten testli; bu dosya kalan ikisini bağlıyor.
// ---------------------------------------------------------------------------

test("gövde üretimi YAPILANDIRILMIŞ blok şeridine düşmez", () => {
  // Canlı arıza (görev b2845b50): `document_generate` seçmiştim.
  // `decideStructuredResponseDecision` onu görünce `document_block` şeması
  // ekliyor → uyumluluk modeli (qwen) seçiliyor → json_validate_failed (400)
  // → "writer content generation failed" → belgeye yine brief yazıldı.
  for (const workload of [WRITER_PROSE_WORKLOAD, WRITER_RESEARCH_WORKLOAD]) {
    const decision = decideStructuredResponseDecision({
      prompt: "Zürafalar hakkında bir rapor metni yaz",
      selectedWorkload: workload,
    });
    assert.notEqual(
      decision.primaryShape,
      "document",
      `${workload} yapılandırılmış belge şeridine düşüyor`,
    );
  }
});

test("gövde iş yükleri gerçekten tanımlı", () => {
  for (const workload of [WRITER_PROSE_WORKLOAD, WRITER_RESEARCH_WORKLOAD]) {
    assert.ok(
      SHARED_BRAIN_WORKLOAD_PROFILES[workload],
      `${workload} iş yükü profili yok`,
    );
  }
});

test("istenen biçim isteğin metninden okunur", () => {
  assert.equal(
    requestedOutputFormat("masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet"),
    "pdf",
  );
  // Türkçe ek toleransı: "pdf'i", "pdfe" gibi biçimler de biçim isteğidir.
  assert.equal(requestedOutputFormat("bunu pdf olarak kaydet"), "pdf");
  assert.equal(
    requestedOutputFormat("masaüstüne zürafalar hakkında bir rapor hazırla"),
    null,
  );
});

test("biçim, gövde yazılırken adıma GERÇEKTEN konuyor", () => {
  // Canlı çıktı (b2845b50): kullanıcı PDF istedi, masaüstü .docx üretti.
  // Plan adımında ne outputFormat ne .pdf uzantılı outputPath vardı.
  const source = readFileSync(
    new URL("./writer-content.ts", import.meta.url).pathname.replace(/\/dist\//, "/src/"),
    "utf8",
  );
  assert.ok(source.includes("requestedOutputFormat("), "biçim hiç okunmuyor");
  assert.ok(
    source.includes("outputFormat: format"),
    "okunan biçim adım argümanlarına yazılmıyor",
  );
});

test("düzyazı yazıcı kümesi tek kaynaktan gelir", () => {
  // Kapılar (boşluk tespiti, içerik doğrulaması, biçim) aynı kümeye bakmalı;
  // biri genişleyip diğeri kalırsa sessiz boşluk doğar.
  assert.ok(PROSE_WRITER_CAPABILITIES.has("document_write"));
  assert.equal(PROSE_WRITER_CAPABILITIES.has("spreadsheet_write"), false);
});
