import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

/**
 * OLGU SEÇİCİSİNİN KAPISI.
 *
 * CANLI ARIZA (2026-08-28, yerel ölçüm): olgusal OLMAYAN her sohbet turu iki
 * olgu sağlayıcısını ağ üzerinden deniyordu. "Fotosentezi 3 cümleyle açıkla."
 * hava durumu sağlayıcısına 0.839 puan alıyordu ve eşik 0.82'ydi. Bedeli
 * ölçüldü: `facts.resolve` p50 767 ms, ilk token'ın ÖNÜNDE — modelin kendi
 * 440 ms'sinden fazla.
 *
 * Bu test gömme modeli gerektirmez; kapının kendisinin — marj eşiğinin —
 * yerinde durduğunu ve ölçülen değerlerin kod içinde belgeli kaldığını
 * doğrular. Uçtan uca ayrım `scripts/` altındaki ölçüm koşusuyla yapılır.
 */

const SOURCE = readFileSync("src/modules/facts/select.ts", "utf8");

test("the shortlist is gated by margin, not by raw score alone", () => {
  // Ham skor tek başına kapı DEĞİLDİR: bu uzayda her istem yüksek puan alır.
  assert.match(SOURCE, /MIN_SELECTION_MARGIN/);
  assert.match(
    SOURCE,
    /top\.score - runnerUp\.score < MIN_SELECTION_MARGIN/,
    "en iyi aday ile ikincisi arasındaki fark kapıyı belirlemeli",
  );
});

test("the margin threshold sits between the measured clusters", () => {
  const match = SOURCE.match(/const MIN_SELECTION_MARGIN = ([\d.]+);/);
  assert.ok(match, "eşik sabiti bulunamadı");
  const threshold = Number(match[1]);

  // Ölçülen dağılım (yorumda tam listesi var):
  //   olgusal DEĞİL → en yüksek marj 0.0061
  //   olgusal       → en düşük marj 0.0174
  // 18 istemlik BİRLEŞİK ölçümde olgusal olmayanların en yüksek marjı 0.0251
  // ("Sen kimsin…"), olgusalların en düşüğü 0.0174 ("Dolar kaç TL?"). Marj
  // TEK BAŞINA ayırmıyor; skor tabanıyla BİRLİKTE ayırıyor.
  assert.ok(
    threshold > 0.0137,
    `eşik ${threshold}, "Bir önceki cevabını kısalt" marjının (0.0137) üstünde olmalı`,
  );
  assert.ok(
    threshold < 0.0174,
    `eşik ${threshold}, olgusalların en düşük marjının (0.0174) altında olmalı`,
  );
});

test("a single candidate is never rejected for lack of a runner-up", () => {
  // Marj tanımsızken kapı uygulanmaz; ölçülemeyen bir sinyal yüzünden turu
  // kısıtlamak, yanlış tarafa düşmek olurdu.
  assert.match(SOURCE, /const runnerUp = scored\[1\];/);
  assert.match(SOURCE, /if \(runnerUp &&/);
});

test("the measured distribution stays written down next to the threshold", () => {
  // Eşik bir tahmin değil, bir ölçümün sonucudur. Ölçüm kaybolursa bir
  // sonraki kişi onu yeniden tahmine çevirir.
  for (const marker of ["0.0174", "Bir önceki cevabını kısalt", "0.8608", "SİMETRİK DEĞİL"]) {
    assert.ok(
      SOURCE.includes(marker),
      `ölçüm kaydı eksik: ${marker}`,
    );
  }
});
