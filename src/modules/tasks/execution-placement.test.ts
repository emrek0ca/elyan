import assert from "node:assert/strict";
import test from "node:test";
import { summarizePlacements, type StepPlacement } from "./execution-placement.js";

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
