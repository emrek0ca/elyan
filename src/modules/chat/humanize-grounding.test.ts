import { strict as assert } from "node:assert";
import { test } from "node:test";
import { isGroundedRewrite } from "./task-sync.js";

// Canlıda görülen gerçek arıza (2026-07-18): connector 4 maili getirdi ama
// humanizer, isteği + "tamamlandı" durumunu görüp veriyi hiç kullanmadan
// "Son dört e-postayı okudum, tamamlandı." uydurdu.

test("contentless source rejects a rich completion claim", () => {
  assert.equal(
    isGroundedRewrite("islem tamam", "Son dört e-postayı okudum, tamamlandı."),
    false,
  );
  assert.equal(
    isGroundedRewrite(
      "Gorev tamamlandi.",
      "Notion notlarınız hazır! Ne eklemek istersiniz?",
    ),
    false,
  );
});

test("generic status words alone never count as grounding", () => {
  // tamam ↔ tamamlandı aynı köke düşer; bilgi taşımadığı için dayanak sayılmaz.
  assert.equal(isGroundedRewrite("tamamlandi", "Tamamlandı, hazır."), false);
});

test("real connector data grounds the rewrite", () => {
  assert.equal(
    isGroundedRewrite(
      "4 e-posta bulundu: PayTR odeme bildirimi, ENUYGUN kampanya",
      "Son 4 e-postan geldi: PayTR ödeme ve ENUYGUN kampanyası.",
    ),
    true,
  );
});

test("legitimate rephrase and honest error relay stay allowed", () => {
  assert.equal(
    isGroundedRewrite(
      "Klasor olusturuldu: Belgeler/Rapor",
      "Belgeler altında Rapor klasörünü oluşturdum.",
    ),
    true,
  );
  assert.equal(
    isGroundedRewrite(
      "Baglanti kurulamadi, yetki suresi doldu",
      "Yetki süresi dolduğu için bağlanamadım.",
    ),
    true,
  );
});

test("Turkish accent and suffix variants still match", () => {
  assert.equal(
    isGroundedRewrite("Fatura goruntulendi", "Faturayı görüntüledim."),
    true,
  );
});
