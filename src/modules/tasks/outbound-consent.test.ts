import assert from "node:assert/strict";
import test from "node:test";
import {
  buildAllowedCapabilities,
  namesExplicitOutboundChannel,
} from "./plan-validators.js";
import type { DesktopWorkOrder } from "./desktop-work-order.js";

// ---------------------------------------------------------------------------
// DIŞARI MESAJ GÖNDERMEK, İSTENMEDİKÇE YAPILMAZ.
//
// Canlı arıza — İKİ görevde de aynı seçim (4d1a9de6, 18eef3db):
//   "masaüstündeki son raporu bul ve telefonuma gönder"
//   → plan adım 2: send_whatsapp_message
// Kullanıcı WhatsApp'tan hiç söz etmemişti. Prompt kuralı eklemek YETMEDİ;
// model "gönder" fiilini görünce elindeki tek gönderme aracına uzanıyor.
//
// Bu bir yetenek tahmini meselesi değil, RIZA meselesidir: istenmeyen bir
// kişiye/kanala mesaj gitmesi geri alınamaz bir yan etkidir.
// ---------------------------------------------------------------------------

function workOrder(summary: string): DesktopWorkOrder {
  return {
    goal: { summary, kind: "desktop_cowork", language: "tr", sourceTextHash: "" },
    requiredCapabilities: [],
  } as unknown as DesktopWorkOrder;
}

test("kanal anılmadıysa giden mesaj kapalı", () => {
  const allowed = buildAllowedCapabilities(
    workOrder("masaüstündeki son raporu bul ve telefonuma gönder"),
  );
  assert.equal(allowed.includes("send_whatsapp_message"), false);
  assert.equal(allowed.includes("email_send"), false);
  // Diğer yetenekler daralmaz.
  assert.ok(allowed.includes("document_write"));
  assert.ok(allowed.includes("file_search"));
});

test("kanal açıkça anıldıysa açılır", () => {
  const whatsapp = buildAllowedCapabilities(
    workOrder("raporu whatsapp'tan abime gönder"),
  );
  assert.ok(whatsapp.includes("send_whatsapp_message"));

  const mail = buildAllowedCapabilities(workOrder("raporu mail olarak gönder"));
  assert.ok(mail.includes("email_send"));
});

test("e-posta adresi de açık kanaldır", () => {
  assert.equal(namesExplicitOutboundChannel("raporu ali@ornek.com adresine at"), true);
});

test("alıcı adı tek başına kanal AÇMAZ", () => {
  // Doğru davranış kanalı tahmin etmek değil, sormaktır.
  assert.equal(namesExplicitOutboundChannel("raporu Ali'ye gönder"), false);
});

test("Türkçe ekler kanalı gizlemez", () => {
  assert.equal(namesExplicitOutboundChannel("whatsapp'tan yolla"), true);
  assert.equal(namesExplicitOutboundChannel("e-postayla gönder"), true);
  assert.equal(namesExplicitOutboundChannel("mesajla ilet"), true);
});

test("boş metin kanal açmaz", () => {
  assert.equal(namesExplicitOutboundChannel(""), false);
  assert.equal(namesExplicitOutboundChannel("masaüstündeki raporu bul"), false);
});
