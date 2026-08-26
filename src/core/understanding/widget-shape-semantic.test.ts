import assert from "node:assert/strict";
import test from "node:test";
import {
  primeWidgetShapeSemantic,
  resetWidgetShapeSemanticCacheForTests,
  resolveWidgetShapeSemantic,
} from "./widget-shape-semantic.js";

test("image is a shape the semantic layer can propose", async () => {
  // Ölçüldü (2026-08-26): "logo tasarla" hiçbir widget'a düşmüyordu, çünkü
  // biçim listesinde `image` YOKTU — katman yapısal olarak görsel öneremiyordu.
  // "Kedi resmi çiz" yalnız `resim` kelimesi bir biçim ipucu ürettiği için
  // kurtuluyordu; kelimeyi kullanmayan her parafraz düşüyordu.
  resetWidgetShapeSemanticCacheForTests();
  await primeWidgetShapeSemantic("logo tasarla");
  assert.equal(resolveWidgetShapeSemantic("logo tasarla")?.shape, "image");

  resetWidgetShapeSemanticCacheForTests();
  await primeWidgetShapeSemantic("bana bir manzara resmi yap");
  assert.equal(
    resolveWidgetShapeSemantic("bana bir manzara resmi yap")?.shape,
    "image",
  );
});

test("adding a seed phrase cannot make an existing seed stop matching", () => {
  // Prototip, tohumların ORTALAMASIYDI. Çeşitlilik arttıkça merkez bulanıyor
  // ve hiçbirine tam benzemiyordu: tablo tohumlarına iki cümle eklendiğinde
  // ZATEN TOHUM OLAN "her birinin fiyatını ve özelliğini düzenli göster"
  // eşleşmez oldu ve mevcut bir test düştü. Listeyi zenginleştirmek doğruluğu
  // DÜŞÜRÜYORDU — tam tersi olması gereken bir davranış.
  //
  // Tohumlar aynı şeyin farklı söylenişleridir, ortalaması alınacak ölçümler
  // değil; benzerlik artık aralarında MAKSİMUM alınıyor. Bu iddia, ileride
  // tohum ekleyen birinin sessizce başka bir ifadeyi kırmasını engeller.
  resetWidgetShapeSemanticCacheForTests();
  for (const seeded of [
    "her birinin fiyatını ve özelliğini düzenli göster",
    "bunları yan yana koyup karşılaştır",
    "bunu excele aktar",
  ]) {
    assert.equal(
      resolveWidgetShapeSemantic(seeded)?.shape,
      "table",
      `tohum eşleşmeli: ${seeded}`,
    );
  }
});
