import assert from "node:assert/strict";
import test from "node:test";
import {
  extractEmailRecipient,
  hasEmailSendIntent,
} from "./local-read-intent.js";

// Canlı arıza (2026-08-26, görev cf4c32d4): kullanıcı "…pdf olarak kaydet
// masaüstüne VE osmanemrekoca@gmail.com a mail olarak gönder" dedi. Üretilen
// menü `web_research, document_write, canvas_write` oldu — mail adımı HİÇ
// yoktu. Gmail bağlıydı, yetenek manifestte vardı; eksik olan tek şey
// mesajdan çıkarım yapan şeritti.

test("açık alıcılı mail isteği tanınır", () => {
  const message =
    "Osmanlı tarihi hakkında 4 sayfalık araştırma metni yaz pdf olarak kaydet masaüstüne ve osmanemrekoca@gmail.com a mail olarak gönder";
  assert.equal(hasEmailSendIntent(message), true);
  assert.equal(extractEmailRecipient(message), "osmanemrekoca@gmail.com");
});

test("ALICI ADRESİ olmadan mail şeridi açılmaz", () => {
  // Adresi tahmin etmek yanlış kişiye mesaj göndermek demektir; geri alınamaz.
  assert.equal(hasEmailSendIntent("bunu birine mail at"), false);
  assert.equal(hasEmailSendIntent("raporu mail olarak gönder"), false);
  assert.equal(extractEmailRecipient("adres yok"), null);
});

test("adres geçse bile mail FİİLİ yoksa açılmaz", () => {
  // "şu adresle ilgili araştır" bir gönderme isteği değildir.
  assert.equal(
    hasEmailSendIntent("osmanemrekoca@gmail.com adresini kaydet"),
    false,
  );
});

test("sıradan üretim isteği mail şeridine düşmez", () => {
  assert.equal(
    hasEmailSendIntent("masaüstüne kediler hakkında rapor hazırla ve kaydet"),
    false,
  );
});
