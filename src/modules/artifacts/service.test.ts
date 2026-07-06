import test from "node:test";
import assert from "node:assert/strict";
import { buildArtifactPipeline } from "./service.js";

test("artifact pipeline builds a validated PDF receipt with footer", async () => {
  const result = await buildArtifactPipeline({
    userRequest:
      "Toplam 18 kapı tamiri =18.000tl Gadet kapı menteşesi =3000tl Genel toplam = 21.000tl En alta Metin cam Metin Koca yazsın.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "pdf");
  assert.equal(result.spec.type, "pdf");
  if (result.spec.type !== "pdf") return;
  assert.equal(result.spec.blocks.filter((block) => block.type === "line_item").length, 2);
  assert.equal(result.spec.blocks.find((block) => block.type === "total")?.amount, 21_000);
  assert.equal(result.spec.footer?.text, "Metin cam Metin Koca");
  assert.equal(result.output.validation.ok, true);
});

test("artifact pipeline builds typed table rows and numeric values", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Şunları tablo yap: Ocak 12000, Şubat 18000, Mart 15000.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "table");
  assert.equal(result.spec.type, "table");
  if (result.spec.type !== "table") return;
  assert.deepEqual(result.spec.columns.map((column) => column.key), ["label", "value"]);
  assert.equal(result.spec.rows.length, 3);
  assert.equal(result.spec.rows[1]?.value, 18_000);
});

test("artifact pipeline builds chart data without fake rows", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Ocak 12000, Şubat 18000, Mart 15000 verisiyle gelir grafiği çiz.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "chart");
  assert.equal(result.spec.type, "chart");
  if (result.spec.type !== "chart") return;
  assert.equal(result.spec.chartType, "bar");
  assert.equal(result.spec.xKey, "label");
  assert.equal(result.spec.yKey, "value");
  assert.equal(result.spec.data.length, 3);
});

test("artifact pipeline builds bounded SVG with text element", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "1024x1024 SVG içinde ortada Elyan yazan sade logo taslağı oluştur.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "svg");
  assert.equal(result.spec.type, "svg");
  if (result.spec.type !== "svg") return;
  assert.equal(result.spec.canvas.width, 1024);
  assert.equal(result.spec.canvas.height, 1024);
  assert.equal(result.spec.canvas.viewBox, "0 0 1024 1024");
  assert.equal(result.spec.elements.some((element) => element.type === "text"), true);
  assert.equal(result.output.output.kind, "svg");
});

test("artifact pipeline renders professional text without unrelated additions", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Bunu daha profesyonel mesaj yap: Abi işi yarın bitiririm.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "text");
  assert.equal(result.spec.type, "text");
  if (result.spec.type !== "text") return;
  assert.equal(result.spec.tone, "formal");
  assert.equal(result.output.output.kind, "text");
  if (result.output.output.kind !== "text") return;
  assert.equal(result.output.output.content, "Merhaba, işi yarın tamamlayacağım.");
});

test("artifact pipeline detects wrong PDF total", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Kapı tamiri 18000 TL, menteşe 3000 TL, genel toplam 22000 TL.",
  });

  assert.equal(result.kind, "rendered");
  if (result.kind !== "rendered") return;
  assert.equal(result.output.type, "pdf");
  assert.equal(result.output.validation.ok, false);
  assert.equal(result.output.validation.errors.some((error) => error.code === "total_mismatch"), true);
  assert.equal(result.spec.type, "pdf");
  if (result.spec.type !== "pdf") return;
  const computed = result.spec.blocks
    .filter((block) => block.type === "line_item")
    .reduce((sum, block) => sum + (block.amount ?? 0), 0);
  assert.equal(computed, 21_000);
});

test("artifact pipeline does not turn ordinary sum questions into PDF", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Bunların toplamı kaç eder?",
  });

  assert.equal(result.kind, "none");
});

test("artifact pipeline requires desktop runtime for private local PDF requests", async () => {
  const result = await buildArtifactPipeline({
    userRequest: "Bilgisayarımdaki son PDF’i özetle ve PDF olarak geri hazırla.",
  });

  assert.equal(result.kind, "desktop_required");
  assert.equal(result.intent.requiresDesktopRuntime, true);
  assert.equal(result.intent.type, "pdf");
});
