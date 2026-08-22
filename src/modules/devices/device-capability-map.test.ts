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
