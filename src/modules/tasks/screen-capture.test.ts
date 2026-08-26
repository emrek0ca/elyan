import assert from "node:assert/strict";
import test from "node:test";
import { hasScreenCaptureIntent } from "./local-read-intent.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";

test("ekran görüntüsü yeteneği manifestte ve DOSYA üretiyor", () => {
  // Canlı arıza (görev 234fbf31): böyle bir yetenek yoktu, istek generic
  // ekran otomasyonuna düşüyor ve dosyasız "başarılı" dönüyordu.
  const entry = DESKTOP_CAPABILITY_MANIFEST.find((item) => item.name === "screen_capture");
  assert.ok(entry, "screen_capture manifestte yok");
  assert.equal(entry?.sideEffectClass, "write");
  // Başarısı "diskte dosya var mı" ile ölçülüyor; bu aynı zamanda
  // `mutatesPath` ve artefakt üretici kümelerini de dolduruyor.
  assert.equal(entry?.mutatesPath, true);
  assert.equal(entry?.requiresApproval, true);
  assert.equal(entry?.requiredArgs.includes("outputPath"), true);
});

test("ekran görüntüsü isteği tanınır", () => {
  assert.equal(hasScreenCaptureIntent("ekran görüntüsünü alıp masaüstüne kaydet"), true);
  assert.equal(hasScreenCaptureIntent("ekranın screenshot'ını al"), true);
  assert.equal(hasScreenCaptureIntent("ekran resmi çek"), true);
});

test("ekranı ANLAMA isteği bu şeride girmez", () => {
  // "ekranda ne var" bir SORUDUR (analyze_screen), "ekran görüntüsü al" bir
  // ÜRETİMDİR. Fiil ayırt eder.
  assert.equal(hasScreenCaptureIntent("ekranda ne var"), false);
  assert.equal(hasScreenCaptureIntent("bu hata ne diyor"), false);
  assert.equal(hasScreenCaptureIntent("ekranı analiz et"), false);
  assert.equal(hasScreenCaptureIntent("ekran görüntüsünde ne yazıyor"), false);
});
