import assert from "node:assert/strict";
import test from "node:test";
import {
  collectStepLocalPaths,
  readClientTargetHint,
  resolveOutputTarget,
} from "./output-target.js";

test("artefakt gerekmiyorsa hedef sohbettir", () => {
  assert.equal(resolveOutputTarget({ artifactRequired: false }), "chat");
});

test("YAZMA KAPSAMI tek başına masaüstü kanıtı DEĞİLDİR", () => {
  // Varsayılan kökler her yazma görevinde açılır; bu yüzden "kapsam var"
  // demek "kullanıcı dosyayı diskinde istiyor" demek değildir. Eskiden
  // hedef bu yüzden masaüstü hiç bağlı olmasa bile `desktop` çıkıyordu.
  assert.equal(
    resolveOutputTarget({
      artifactRequired: true,
      writeRoots: ["workspace", "~/Desktop", "~/Documents", "~/Downloads"],
      route: "desktop_runtime",
      desktopDeliveryRequested: false,
    }),
    "artifact",
  );
});

test("açık yerel teslim isteği masaüstü hedefi üretir", () => {
  assert.equal(
    resolveOutputTarget({
      artifactRequired: true,
      writeRoots: ["~/Desktop"],
      route: "desktop_runtime",
      desktopDeliveryRequested: true,
    }),
    "desktop",
  );
});

test("planın somut yerel yolu da teslim kanıtıdır", () => {
  assert.equal(
    resolveOutputTarget({
      artifactRequired: true,
      writeRoots: ["~/Desktop"],
      route: "desktop_runtime",
      stepLocalPaths: ["~/Desktop/rapor.docx"],
    }),
    "desktop",
  );
});

test("masaüstüne gitmeyen tur asla desktop hedefi almaz", () => {
  assert.equal(
    resolveOutputTarget({
      artifactRequired: true,
      writeRoots: ["~/Desktop"],
      route: "server_brain",
      desktopDeliveryRequested: true,
      stepLocalPaths: ["~/Desktop/x.docx"],
    }),
    "artifact",
  );
});

test("İSTEMCİ İPUCU asla masaüstü yazma yetkisi üretemez", () => {
  // İstemci "bunu bana ver" diyebilir; "kullanıcının diskine yaz" diyemez.
  assert.equal(readClientTargetHint({ preferredTarget: "desktop" }), null);
  assert.equal(readClientTargetHint({ outputMode: "desktop" }), null);
  assert.equal(readClientTargetHint({ mobileDocumentExport: true }), "artifact");
  assert.equal(readClientTargetHint({ documentExportMode: "on_device" }), "artifact");
  assert.equal(readClientTargetHint(undefined), null);
});

test("yalnız ev dizinine çapalı yollar teslim kanıtı sayılır", () => {
  assert.deepEqual(
    collectStepLocalPaths({
      planPreview: {
        steps: [
          { capability: "document_write", args: { outputPath: "~/Desktop/a.docx" } },
          { capability: "x", resourceScope: ["workspace"], args: {} },
        ],
      },
    }),
    ["~/Desktop/a.docx"],
  );
  assert.deepEqual(collectStepLocalPaths(null), []);
  assert.deepEqual(collectStepLocalPaths({ planPreview: { steps: [] } }), []);
});
