import assert from "node:assert/strict";
import test from "node:test";
import { isFactualKnowledgeQuestion } from "./service.js";

// Canlı arıza (2026-08-25, görev fb131ded): "Osmanlının son padişahı kimdi
// biraz anlatır mısın" hızlı şeride düştü ve cevap "Osmanlı Devleti'nin son
// padişahı III. Mehmet, yani 'Koca' Mehmet V." oldu — üç padişah adı tek
// cümlede karışmış, hepsi yanlış (doğrusu Mehmed VI / Vahdettin). Hızlı şerit
// 384 token tavanlı ve kodun kendi yorumunda selamlaşma/small-talk için
// ayrılmış; tarihsel bir olgu oraya gitmemeli.

test("VARLIK/TARİH hatırlama + anlatım isteği yükseltilir", () => {
  assert.equal(
    isFactualKnowledgeQuestion("Merhaba osmanlının son padişahi kimdi biraz anlatır mısın"),
    true,
  );
  assert.equal(
    isFactualKnowledgeQuestion("Fatih Sultan Mehmet kimdir, detaylı anlat"),
    true,
  );
  assert.equal(
    isFactualKnowledgeQuestion("Çanakkale savaşı ne zaman oldu, biraz açıklar mısın"),
    true,
  );
});

test("KAVRAMSAL açıklama hızlı şeritte kalır", () => {
  // Küçük modelin uydurma riski, hatırlanacak bir OLGUDA yüksek; kavramsal
  // bir açıklamada değil. Ürün kararı da bunu hızlı şeritte tutuyor.
  assert.equal(
    isFactualKnowledgeQuestion("Paragraf halinde anlat: veri normalizasyonu ne işe yarar?"),
    false,
  );
  assert.equal(isFactualKnowledgeQuestion("Bu konuyu kısaca anlat, tablo istemiyorum"), false);
  assert.equal(isFactualKnowledgeQuestion("Kuantum dolanıklığını açıklar mısın"), false);
});

test("BASİT olgu soruları hızlı şeritte KALIR", () => {
  // Ürün kararı: kısa cevaplı olgu soruları hızlı profilde kalmalı. Yükseltmeyi
  // hak eden şey kullanıcının ANLATIM istemesidir — 384 token bir açıklamayı
  // taşıyamaz, model boşluğu uydurmayla doldurur.
  assert.equal(isFactualKnowledgeQuestion("İstanbul ne zaman fethedildi?"), false);
  assert.equal(isFactualKnowledgeQuestion("Fotosentez nedir"), false);
  assert.equal(isFactualKnowledgeQuestion("Einstein nereli"), false);
});

test("SORU BİÇİMİ olmadan kapı açılmaz", () => {
  assert.equal(isFactualKnowledgeQuestion("kime gideceğimi biliyorum"), false);
  assert.equal(isFactualKnowledgeQuestion("rapor hazırla"), false);
  assert.equal(isFactualKnowledgeQuestion(""), false);
});

test("açıklama isteği TEK BAŞINA yetmez", () => {
  // Soru işareti tek başına kapı olsaydı sıradan sohbetin yarısı balanced'a
  // kayardı; ortada hatırlanacak bir olgu da olmalı.
  assert.equal(isFactualKnowledgeQuestion("Bunu biraz açıklar mısın"), false);
  assert.equal(isFactualKnowledgeQuestion("detaylı anlatır mısın"), false);
});
