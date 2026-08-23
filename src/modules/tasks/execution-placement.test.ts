import assert from "node:assert/strict";
import test from "node:test";
import {
  buildPlacementSnapshot,
  isDesktopPlacementReady,
  summarizePlacements,
  unplaceableSteps,
  type StepPlacement,
} from "./execution-placement.js";
import type { DeviceCapabilityView } from "../devices/device-capability-map.js";

// ---------------------------------------------------------------------------
// Notion §5: koordinatörün sorması gereken sıra —
//   gerekli capability → hangi cihazlarda var → veri nerede → izin → cihaz açık
//
// Yerleştirme ÖNCE GÖLGEDE çalışır: karar kaydedilir, yürütme değişmez.
// Sebep: bu oturumda çalışan bir yolu yenisiyle değiştirmek 9 gizli regresyon
// üretti. Yerleştirme önce kendini sayıyla kanıtlamalı.
// ---------------------------------------------------------------------------

function placement(overrides: Partial<StepPlacement>): StepPlacement {
  return {
    stepId: "s1",
    capability: "document_write",
    basis: "declared_online",
    device: "desktop",
    online: true,
    ...overrides,
  };
}

test("özet çözülen ve çözülemeyeni ayırır", () => {
  const summary = summarizePlacements([
    placement({ stepId: "s1" }),
    placement({ stepId: "s2", device: "mobile", capability: "present_file", basis: "baseline_online" }),
    placement({ stepId: "s3", capability: "quantum_teleport", basis: "unresolved", device: undefined, online: undefined }),
  ]);
  assert.equal(summary.total, 3);
  assert.equal(summary.resolved, 2);
  assert.equal(summary.unresolved, 1);
  assert.deepEqual(summary.byDevice, { desktop: 1, mobile: 1 });
});

test("çevrimdışı yerleşim ayrı sayılır", () => {
  // "Cihaz kapalı" ile "yetenek yok" ayrı sorunlardır; ölçüm ikisini karıştırmaz.
  const summary = summarizePlacements([
    placement({ basis: "declared_offline", online: false }),
  ]);
  assert.equal(summary.resolved, 1);
  assert.equal(summary.offline, 1);
  assert.equal(summary.unresolved, 0);
});

test("boş plan sıfır döner", () => {
  const summary = summarizePlacements([]);
  assert.equal(summary.total, 0);
  assert.equal(summary.resolved, 0);
  assert.deepEqual(summary.byDevice, {});
});

test("shadow snapshot only carries bounded placement evidence", () => {
  const snapshot = buildPlacementSnapshot(
    [
      placement({ stepId: "s1", deviceId: "mac" }),
      placement({
        stepId: "s2",
        capability: "present_file",
        device: "mobile",
        basis: "baseline_online",
      }),
      placement({
        stepId: "s3",
        capability: "send_whatsapp_message",
        basis: "unresolved",
        device: undefined,
        online: undefined,
      }),
    ],
    "2030-01-01T00:00:00.000Z",
  );
  assert.deepEqual(snapshot, {
    mode: "shadow",
    resolvedAt: "2030-01-01T00:00:00.000Z",
    summary: {
      total: 3,
      resolved: 2,
      unresolved: 1,
      offline: 0,
      byDevice: { desktop: 1, mobile: 1 },
    },
    unresolvedCapabilities: ["send_whatsapp_message"],
  });
});

test("yalnız çevrimiçi runtime desktop yerleşimi bağlanabilir", () => {
  assert.equal(
    isDesktopPlacementReady({ placements: [placement({})] }),
    true,
  );
  assert.equal(
    isDesktopPlacementReady({
      placements: [placement({ basis: "baseline_online" })],
    }),
    false,
  );
  assert.equal(
    isDesktopPlacementReady({
      placements: [placement({ device: "mobile" })],
    }),
    false,
  );
  assert.equal(
    isDesktopPlacementReady({
      placements: [placement({ basis: "declared_offline", online: false })],
    }),
    false,
  );
});

// ---------------------------------------------------------------------------
// HİÇBİR CİHAZDA ÇALIŞAMAYACAK ADIM GÖNDERİLMEZ.
//
// Canlı arıza (görev 4d1a9de6): plan iki adımdı —
//   1. file_search            → çalıştı
//   2. send_whatsapp_message  → hiçbir cihazda YOK → FILE_NOT_FOUND
// Yerleştirme bunu ÖNCEDEN biliyordu; kimse okumuyordu.
// ---------------------------------------------------------------------------

function declaredMap(): DeviceCapabilityView[] {
  return [
    {
      deviceId: "mac",
      platform: "macos",
      kind: "desktop",
      online: true,
      capabilities: ["file.search"],
      source: "runtime_declared",
    },
  ];
}

test("yerleşemeyen adım bildirilir", () => {
  const unplaceable = unplaceableSteps({
    map: declaredMap(),
    placements: [
      placement({ stepId: "s1", capability: "file_search" }),
      placement({
        stepId: "s2",
        capability: "send_whatsapp_message",
        basis: "unresolved",
        device: undefined,
        online: undefined,
      }),
    ],
  });
  assert.equal(unplaceable.length, 1);
  assert.equal(unplaceable[0].capability, "send_whatsapp_message");
});

test("hiçbir cihaz beyan etmemişse kapı SUSAR", () => {
  // Bilgi eksikliği yüzünden tüm görevleri öldürmek, hatayı düzeltmez.
  const unplaceable = unplaceableSteps({
    map: [
      {
        deviceId: "phone",
        platform: "ios",
        kind: "mobile",
        online: true,
        capabilities: ["camera"],
        source: "platform_baseline",
      },
    ],
    placements: [
      placement({ stepId: "s1", capability: "file_search", basis: "unresolved", device: undefined }),
    ],
  });
  assert.deepEqual(unplaceable, []);
});

test("mobil istemci beyanı readiness handshake gelene kadar gölgede kalır", () => {
  const unplaceable = unplaceableSteps({
    map: [
      {
        deviceId: "phone",
        platform: "ios",
        kind: "mobile",
        online: false,
        capabilities: ["present_file"],
        source: "client_declared",
      },
    ],
    placements: [
      placement({
        stepId: "s1",
        capability: "unsupported_capability",
        basis: "unresolved",
        device: undefined,
        online: undefined,
      }),
    ],
  });
  assert.deepEqual(unplaceable, []);
});

test("her adım yerleştiyse kapı sessiz", () => {
  assert.deepEqual(
    unplaceableSteps({
      map: declaredMap(),
      placements: [placement({ stepId: "s1", capability: "file_search" })],
    }),
    [],
  );
});
