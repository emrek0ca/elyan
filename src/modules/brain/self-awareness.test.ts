import assert from "node:assert/strict";
import test from "node:test";
import { buildEcosystemContextBlock } from "./ecosystem-context.js";

/**
 * ELYAN KENDİ KISITINI BİLMELİ — VE YALNIZ GERÇEK OLANI.
 *
 * Gömme işçisi öldüğünde kaynak seçimi kelime eşleşmesine düşüyor, cevap
 * sessizce kötüleşiyor ve Elyan bunu bilmediği için kullanıcıya da
 * söyleyemiyordu. Üretimde tam olarak bu yaşandı (`ERR_DLOPEN_FAILED`).
 */
test("a degraded layer is stated in the prompt, honestly", () => {
  const block = buildEcosystemContextBlock({
    desktopPaired: null,
    degraded: { knowledgeSelectionBlind: true },
  });
  assert.match(block, /ŞU ANKİ KISITIN/);
  assert.match(block, /kelime eşleşmesiyle/);
  // Uydurma gerekçe vermemesi AÇIKÇA söylenmeli: kısıtı bilmek, onu
  // rasyonelleştirmeye davet değildir.
  assert.match(block, /uydurma bir gerekçe verme/);
});

/**
 * SAĞLAM TURDA SESSİZ KALIR. Her turda "her şey yolunda" demek gürültüdür ve
 * modelin dikkatini böler; modülün kendi ilkesi de bu ("bilinmiyorsa hiçbir
 * şey iddia edilmez").
 */
test("a healthy turn says nothing about limits", () => {
  for (const degraded of [
    undefined,
    { knowledgeSelectionBlind: false },
  ]) {
    const block = buildEcosystemContextBlock({ desktopPaired: null, degraded });
    assert.ok(
      !block.includes("ŞU ANKİ KISITIN"),
      "bozulma yokken kısıt cümlesi eklenmemeli",
    );
  }
});

test("the environment block still describes the runtime itself", () => {
  const block = buildEcosystemContextBlock({ desktopPaired: true });
  assert.match(block, /ÇALIŞMA ORTAMIN/);
  assert.match(block, /masaüstü cihazı BAĞLI/);
});
