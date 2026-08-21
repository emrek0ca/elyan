import assert from "node:assert/strict";
import test from "node:test";
import {
  isLocalActionCapability,
  localActionCapabilityNames,
} from "./desktop-capability-embedding-match.js";

// ---------------------------------------------------------------------------
// "Bu iş kullanıcının makinesinde gerçekten bir şey yapar mı?" sorusunun cevabı
// MANİFESTTEN türetilir — elle liste tutulmaz.
//
// Canlı arıza (2026-08-22): "Müslüm gürsesden bir şeyler çal" sohbete düştü.
// `play_media` masaüstünde vardı, eşleştirici onu 1.000 skor / 0.316 marjla
// birinci veriyordu, ama yönlendirme yetenek uzayına hiç sormuyordu; üstelik
// elle tutulan `DESKTOP_ONLY_CAPABILITIES` listesinde `play_media` YOKTU.
// ---------------------------------------------------------------------------

test("machine-acting capabilities are recognised as local actions", () => {
  for (const capability of [
    "play_media",
    "open_app",
    "close_app",
    "browser_control",
    "shell_run",
    "email_send",
    "add_calendar_event",
  ]) {
    assert.equal(
      isLocalActionCapability(capability),
      true,
      `${capability} yerel eylem sayılmadı`,
    );
  }
});

test("server-capable work is never treated as a local action", () => {
  // Bunlar ölçümde yüksek marjla top-1 çıkabiliyor; yerel-eylem şartı olmasa
  // hava durumu sorusu masaüstüne giderdi (get_weather, marj 0.695).
  for (const capability of [
    "get_weather",
    "image_generate",
    "web_research",
    "document_write",
    "chart_generate",
  ]) {
    assert.equal(
      isLocalActionCapability(capability),
      false,
      `${capability} yanlışlıkla yerel eylem sayıldı`,
    );
  }
});

test("the local action set stays small and manifest-derived", () => {
  const names = localActionCapabilityNames();
  assert.ok(names.includes("play_media"));
  // Manifest büyüdükçe küme de büyür; ama bu küme "her masaüstü yeteneği"
  // olmamalı — öyle olursa yönlendirme kanıtı anlamını yitirir.
  assert.ok(names.length >= 8 && names.length <= 24, `beklenmedik boyut: ${names.length}`);
  assert.equal(names.includes("get_weather"), false);
});
