import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * KAPI HANGİ AŞAMAYA BAKIYOR?
 *
 * Bu kapı uzun süre SÖZCÜKSEL katmanı ölçtü; üretim yolu (sözcüksel + e5)
 * yalnız `--full` ile koşuyordu ve kimse koşmuyordu. Sonuç: "genelleme payı
 * 40,6 puan" diye raporlanan sayı üretimin kararının değildi. Aynı anda
 * ölçüldüğünde üretim yolu korpus 99.0% → tutulan 83.0% (16,1 puan) veriyordu.
 *
 * Bu testler o hatanın geri gelmesini engeller.
 */
const source = readFileSync(new URL("./routing-eval-report.ts", import.meta.url), "utf8");

describe("yönlendirme kapısı", () => {
  it("üretim yolunu bir bayrağın arkasına saklamaz", () => {
    expect(source).not.toContain('includes("--full")');
    expect(source).toContain('includes("--lexical-only")');
  });

  it("üretim ölçümünü varsayılan koşuda yapar", () => {
    const guard = source.indexOf("if (!lexicalOnly) {");
    expect(guard).toBeGreaterThan(-1);
    const body = source.slice(guard, guard + 900);
    expect(body).toContain("runFullPipelineEval(ROUTING_EVAL_CORPUS)");
    expect(body).toContain("runFullPipelineEval(ROUTING_EVAL_HELDOUT)");
  });

  it("e5 hazır değilse sessizce sözcüksel sayıya düşmez", () => {
    expect(source).toContain("isDesktopCapabilityVectorCacheReady()");
    expect(source).toContain("ÜRETİM YOLU ÖLÇÜLEMEDİ");
    expect(source).toContain("process.exitCode = 1");
  });

  it("başlık sayısını üretim yolu olarak etiketler", () => {
    expect(source).toContain("GENELLEME PAYI (ÜRETİM)");
    expect(source).toContain("[BİLEŞEN] sözcüksel katman");
  });
});
