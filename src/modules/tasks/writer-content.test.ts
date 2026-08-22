import assert from "node:assert/strict";
import test from "node:test";
import {
  WRITER_CONTENT_MIN_WORDS,
  findWriterContentGap,
} from "./writer-content.js";
import type { DesktopWorkOrderStep } from "./desktop-work-order.js";

// ---------------------------------------------------------------------------
// CANLI ARIZA (görev fd3acf73, 2026-08-22).
//
// "masaüstüne kediler hakkında bir rapor hazırla ve kaydet" isteğinde plan tek
// adım oldu ve `prompt` alanına 21 kelimelik KONU TARİFİ kondu. Masaüstü
// yazıcısı içerik üretmediği için belgeye o tarif aynen yazıldı: başlık + brief.
//
// Planlayıcı gövdeyi yazamaz — ölçüm: plan cevabı 309 / onarımda 100 token,
// iki sayfalık Türkçe metin ~800–1.200 token.
// ---------------------------------------------------------------------------

function step(overrides: Partial<DesktopWorkOrderStep> = {}): DesktopWorkOrderStep {
  return {
    id: "s1",
    capability: "document_write",
    description: "Belge yaz",
    args: {},
    ...overrides,
  } as DesktopWorkOrderStep;
}

const LIVE_BRIEF =
  "Kedilerin tarihçesi, tür çeşitliliği, bakım önerileri ve ilginç gerçekler hakkında iki sayfalık bir rapor. Giriş, ana bölümler ve sonuç kısmı içersin.";

test("canlı arızadaki brief gövde sayılmaz", () => {
  const gap = findWriterContentGap(
    step({ args: { title: "Kediler Hakkında Rapor", prompt: LIVE_BRIEF } }),
  );
  assert.ok(gap, "21 kelimelik tarif gövde sayıldı — arıza geri geldi");
  assert.equal(gap?.argKey, "prompt");
  assert.ok((gap?.words ?? 0) < WRITER_CONTENT_MIN_WORDS);
});

test("gerçek gövde olduğunda dokunulmaz", () => {
  const body = Array.from({ length: WRITER_CONTENT_MIN_WORDS + 40 }, () => "kelime").join(" ");
  assert.equal(findWriterContentGap(step({ args: { prompt: body } })), null);
});

test("adım referansı olan plana dokunulmaz", () => {
  // Plan doğru kurulmuş: içerik önceki adımdan akıyor. Üzerine yazmak bozar.
  assert.equal(
    findWriterContentGap(step({ args: { prompt: "{{steps.arastirma.output}}" } })),
    null,
  );
  assert.equal(
    findWriterContentGap(step({ args: { sourceContext: "Arastirma: {{steps.s1.output}}" } })),
    null,
  );
});

test("yapılandırılmış gövde varsa dokunulmaz", () => {
  assert.equal(
    findWriterContentGap(
      step({ args: { sections: [{ heading: "Giriş", body: "..." }] } }),
    ),
    null,
  );
  assert.equal(
    findWriterContentGap(
      step({ capability: "presentation_write", args: { slides: [{ title: "A" }] } }),
    ),
    null,
  );
});

test("düzyazı olmayan yazıcı kapsam dışında", () => {
  // spreadsheet_write yapılandırılmış satır/sütun ister; oraya düzyazı üretmek
  // yanlış olur. Kapsam bilinçli olarak dar.
  assert.equal(
    findWriterContentGap(
      step({ capability: "spreadsheet_write", args: { prompt: "3 aylık bütçe" } }),
    ),
    null,
  );
  assert.equal(
    findWriterContentGap(step({ capability: "open_app", args: { app_name: "Chrome" } })),
    null,
  );
});

test("boş yazıcı adımı da eksik sayılır", () => {
  const gap = findWriterContentGap(step({ args: { outputPath: "~/Desktop/x.docx" } }));
  assert.ok(gap);
  assert.equal(gap?.words, 0);
  assert.equal(gap?.argKey, "prompt");
});

test("canvas_write da düzyazı yazıcısıdır", () => {
  assert.ok(findWriterContentGap(step({ capability: "canvas_write", args: { prompt: "kısa" } })));
});
