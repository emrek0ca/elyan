import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// ---------------------------------------------------------------------------
// KAPI HANGİ AŞAMAYA BAKIYOR?
//
// Bu kapı uzun süre SÖZCÜKSEL katmanı ölçtü; üretim yolu (sözcüksel + e5)
// yalnız `--full` ile koşuyordu ve pratikte hiç koşulmuyordu. Sonuç: "genelleme
// payı 40,6 puan" diye raporlanan sayı üretimin verdiği kararın değildi. Aynı
// anda ölçüldüğünde üretim yolu korpus 99.0% → tutulan 83.0% (16,1 puan)
// veriyordu. Bu testler o hatanın geri gelmesini engeller.
// ---------------------------------------------------------------------------

const source = readFileSync(
  new URL("../../src/scripts/routing-eval-report.ts", import.meta.url),
  "utf8",
);

test("üretim yolu bir bayrağın arkasına saklanmaz", () => {
  assert.equal(source.includes('includes("--full")'), false);
  assert.ok(source.includes('includes("--lexical-only")'));
});

test("üretim ölçümü varsayılan koşuda yapılır", () => {
  const guard = source.indexOf("if (!lexicalOnly) {");
  assert.ok(guard > -1, "lexicalOnly koruması bulunamadı");
  const body = source.slice(guard, guard + 900);
  assert.ok(body.includes("runFullPipelineEval(ROUTING_EVAL_CORPUS)"));
  assert.ok(body.includes("runFullPipelineEval(ROUTING_EVAL_HELDOUT)"));
});

test("e5 hazır değilse sessizce sözcüksel sayıya düşülmez", () => {
  assert.ok(source.includes("isDesktopCapabilityVectorCacheReady()"));
  assert.ok(source.includes("ÜRETİM YOLU ÖLÇÜLEMEDİ"));
  assert.ok(source.includes("process.exitCode = 1"));
});

test("başlık sayısı üretim yolu olarak etiketlenir", () => {
  assert.ok(source.includes("GENELLEME PAYI (ÜRETİM)"));
  assert.ok(source.includes("[BİLEŞEN] sözcüksel katman"));
});
