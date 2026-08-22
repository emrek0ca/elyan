import assert from "node:assert/strict";
import test from "node:test";
import { placeCapability, type DeviceCapabilityView } from "./device-capability-map.js";

// ---------------------------------------------------------------------------
// HANGİ YETENEK HANGİ CİHAZDA?
//
// Ölçüm (2026-08-22): masaüstü 102 yetenek beyan ediyor, MOBİL hiç beyan
// etmiyor. Planlayıcı "kamera/konum/paylaşım mobilde" bilgisine sahip değildi;
// "bilgisayarımdaki faturayı bul ve telefona gönder" isteğini cihazlara
// bölememesinin sebebi buydu.
// ---------------------------------------------------------------------------

function device(
  overrides: Partial<DeviceCapabilityView> & { deviceId: string },
): DeviceCapabilityView {
  return {
    platform: "ios",
    kind: "mobile",
    online: true,
    capabilities: [],
    source: "none",
    ...overrides,
  };
}

test("yetenek doğru cihazda bulunur", () => {
  const map = [
    device({ deviceId: "mac", platform: "macos", kind: "desktop", capabilities: ["shell_run", "document_write"], source: "runtime_declared" }),
    device({ deviceId: "phone", capabilities: ["camera", "share"], source: "platform_baseline" }),
  ];
  assert.deepEqual(
    placeCapability(map, "camera").map((p) => p.deviceId),
    ["phone"],
  );
  assert.deepEqual(
    placeCapability(map, "shell_run").map((p) => p.deviceId),
    ["mac"],
  );
});

test("çevrimiçi cihaz önce gelir ama çevrimdışı da DÖNER", () => {
  // "Yetenek yok" ile "cihaz şu an kapalı" aynı şey değildir; ikisini aynı
  // saymak kullanıcıya "yapamıyorum" demekle "ulaşamıyorum" demeyi karıştırır.
  const map = [
    device({ deviceId: "eski-mac", platform: "macos", kind: "desktop", online: false, capabilities: ["shell_run"] }),
    device({ deviceId: "yeni-mac", platform: "macos", kind: "desktop", online: true, capabilities: ["shell_run"] }),
  ];
  const placements = placeCapability(map, "shell_run");
  assert.equal(placements.length, 2);
  assert.equal(placements[0].deviceId, "yeni-mac");
  assert.equal(placements[0].online, true);
  assert.equal(placements[1].online, false);
});

test("bilinmeyen yetenek boş döner", () => {
  assert.deepEqual(placeCapability([device({ deviceId: "phone" })], "quantum_teleport"), []);
  assert.deepEqual(placeCapability([], "camera"), []);
});

test("yetenek kaynağı bildirilir", () => {
  const map = [device({ deviceId: "phone", capabilities: ["camera"], source: "platform_baseline" })];
  assert.equal(placeCapability(map, "camera")[0].source, "platform_baseline");
});

// ---------------------------------------------------------------------------
// CANLI ARIZA (görev 4d1a9de6, 2026-08-22 19:18).
//
// Gölge yerleştirmesi: resolved 0 / unresolved 2 —
//   unresolvedCapabilities: ["file_search", "send_whatsapp_message"]
// Oysa masaüstü 102 yetenek beyan ediyordu ve içlerinde `file.search` VARDI.
//
// Çalışma zamanı NOKTA ile beyan ediyor (`document.write`), planlar ALT ÇİZGİ
// kullanıyor (`document_write`). İki isimlendirme sözleşmesi, aynı yetenek.
// ---------------------------------------------------------------------------

test("nokta ve alt çizgi yazımı aynı yeteneği bulur", () => {
  const map = [
    device({
      deviceId: "mac",
      platform: "macos",
      kind: "desktop",
      source: "runtime_declared",
      capabilities: ["file.search", "document.write", "desktop.operator.observe.screen"],
    }),
  ];
  assert.equal(placeCapability(map, "file_search")[0]?.deviceId, "mac");
  assert.equal(placeCapability(map, "document_write")[0]?.deviceId, "mac");
  // Plan adı ikisini birden içerebiliyor; saf çeviri yetmez.
  assert.equal(
    placeCapability(map, "desktop_operator.observe_screen")[0]?.deviceId,
    "mac",
  );
});

test("gerçekten olmayan yetenek yine bulunmaz", () => {
  const map = [
    device({ deviceId: "mac", kind: "desktop", capabilities: ["file.search"] }),
  ];
  assert.deepEqual(placeCapability(map, "send_whatsapp_message"), []);
});
