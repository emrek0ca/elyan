import assert from "node:assert/strict";
import test from "node:test";
import { buildLocalRenderRecipe } from "./render-recipe.js";

test("buildLocalRenderRecipe returns null for plain chat", () => {
  assert.equal(
    buildLocalRenderRecipe({
      prompt: "Merhaba Elyan",
      responseText: "Merhaba!",
    }),
    null,
  );
});

test("buildLocalRenderRecipe emits a document render recipe for PDF export prompts", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Metni PDF olarak ver",
    responseText: "Başlık\n\nBirinci paragraf",
    metadata: {
      renderOn: "mobile",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.schema_version, "2026-06-mobile-render-recipe-v2");
  assert.equal(recipe?.output_type, "document_render_recipe");
  assert.equal(recipe?.format, "pdf");
  assert.equal(recipe?.mime_type, "application/pdf");
  assert.match(recipe?.file_name ?? "", /\.pdf$/);
  assert.equal(recipe?.render_on, "mobile");
  assert.equal(recipe?.layout.kind, "document_page");
  assert.equal(recipe?.text_blocks[0]?.text, "Başlık");
  assert.equal(recipe?.content_model.language, "tr");
  assert.equal(recipe?.render_hints.renderer, "mobile_local");
  assert.equal(recipe?.render_hints.allow_print, true);
});

test("buildLocalRenderRecipe emits a document render recipe for PDF yap prompts", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "PDF yap",
    responseText: "Başlık\n\nBirinci paragraf",
    metadata: {
      renderOn: "mobile",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.output_type, "document_render_recipe");
  assert.equal(recipe?.format, "pdf");
  assert.equal(recipe?.render_on, "mobile");
});

test("buildLocalRenderRecipe emits an image render recipe when asked for visuals", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Bunu görsel olarak PNG üret",
    responseText: "Açıklama\n\n- Madde 1",
    metadata: {
      exportFormat: "png",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.output_type, "image_render_recipe");
  assert.equal(recipe?.format, "png");
  assert.equal(recipe?.mime_type, "image/png");
  assert.equal(recipe?.layout.kind, "canvas");
  assert.equal(recipe?.render_on, "mobile");
  assert.equal(recipe?.render_hints.allow_print, false);
});

test("buildLocalRenderRecipe emits an image render recipe for visual production prompts", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Görsel üret",
    responseText: "Açıklama\n\n- Madde 1",
    metadata: {
      exportFormat: "png",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.output_type, "image_render_recipe");
  assert.equal(recipe?.format, "png");
});

test("buildLocalRenderRecipe preserves explicit SVG image export format", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Bu içeriği SVG olarak ver",
    responseText: "Başlık\n\nAkış diyagramı açıklaması",
    metadata: {
      documentExportMode: "mobile_local",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.output_type, "image_render_recipe");
  assert.equal(recipe?.format, "svg");
  assert.equal(recipe?.mime_type, "image/svg+xml");
  assert.equal(recipe?.layout.kind, "canvas");
  assert.equal(recipe?.render_hints.vector_safe, true);
  assert.equal(recipe?.render_hints.fallback_format, "png");
});

test("buildLocalRenderRecipe preserves explicit JPG image export format", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Bunu jpg görsel olarak hazırla",
    responseText: "Görsel metni",
  });

  assert.ok(recipe);
  assert.equal(recipe?.output_type, "image_render_recipe");
  assert.equal(recipe?.format, "jpg");
  assert.equal(recipe?.mime_type, "image/jpeg");
});

test("buildLocalRenderRecipe exposes structured blocks for mobile canvas rendering", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Bunu PNG görsel olarak oluştur",
    responseText:
      "Veri Akışı\n\n- Girdi alınır\n- Anlam çıkarılır\n- Çıktı üretilir",
    metadata: {
      documentExportMode: "mobile_local",
      title: "Veri Akışı",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.file_name, "veri-akışı.png");
  assert.equal(recipe?.content_model.title, "Veri Akışı");
  assert.equal(recipe?.content_model.block_count, 4);
  assert.equal(
    recipe?.text_blocks.filter((block) => block.type === "bullet").length,
    3,
  );
  assert.equal(recipe?.metadata.render_intent, "raster_image_export");
});

test("buildLocalRenderRecipe preserves explicit XLSX export format", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Bunu xlsx olarak hazırla",
    responseText: "Özet\n\n| İsim | Değer |\n| --- | --- |\n| A | 12 |",
    metadata: {
      documentExportMode: "mobile_local",
      title: "Veri Özeti",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.output_type, "document_render_recipe");
  assert.equal(recipe?.format, "xlsx");
  assert.equal(
    recipe?.mime_type,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  );
  assert.match(recipe?.file_name ?? "", /\.xlsx$/);
});

test("buildLocalRenderRecipe prefers structured assistant blocks over preface prose for document exports", () => {
  const recipe = buildLocalRenderRecipe({
    prompt: "Bunu PDF olarak ver",
    responseText: "Raporu hazırladım. Aşağıda belge var.",
    assistantBlocks: [
      {
        type: "document_block",
        title: "Yapay Zeka Raporu",
        sections: [
          {
            heading: "Giriş",
            content: "**Tanım**\n\n- İlk madde\n- İkinci madde",
            level: 1,
          },
        ],
      },
      {
        type: "table",
        title: "Karşılaştırma",
        columns: ["Alan", "Etki"],
        rows: [["Sağlık", "Yüksek"]],
      },
    ],
    metadata: {
      documentExportMode: "mobile_local",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.content_model.title, "Yapay Zeka Raporu");
  assert.equal(recipe?.text_blocks[0]?.type, "title");
  assert.equal(recipe?.text_blocks[0]?.text, "Yapay Zeka Raporu");
  assert.equal(
    recipe?.text_blocks.some((block) => block.type === "table"),
    true,
  );
  assert.equal(
    recipe?.content_model.plain_text.includes("Raporu hazırladım"),
    false,
  );
  assert.equal(recipe?.content_model.plain_text.includes("Tanım"), true);
});

test("buildLocalRenderRecipe carries PDF footer and business style as typed metadata", () => {
  const recipe = buildLocalRenderRecipe({
    prompt:
      "Toplam 18 kapı tamiri 18.000 TL. Bunu resmi teklif PDF yap, en alt kısmında Metin cam Metin koca yazsın",
    responseText:
      "Kapı tamiri: 18.000 TL\nMenteşe: 3.000 TL\nGenel toplam: 21.000 TL",
    metadata: {
      documentExportMode: "mobile_local",
    },
  });

  assert.ok(recipe);
  assert.equal(recipe?.format, "pdf");
  assert.equal(recipe?.metadata.document_style, "formal");
  assert.equal(recipe?.metadata.document_kind, "quote");
  assert.equal(recipe?.metadata.layout_template, "business_document");
  assert.equal(recipe?.metadata.footer_text, "Metin cam Metin koca");
  assert.equal(recipe?.metadata.preflight_required, true);
  assert.deepEqual(recipe?.metadata.required_markers, [
    "Kapı tamiri: 18.000 TL Menteşe: 3.000 TL Genel toplam: 21.000 TL",
    "Metin cam Metin koca",
  ]);
});
