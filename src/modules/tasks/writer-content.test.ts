import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  WRITER_CONTENT_MIN_WORDS,
  findWriterContentGap,
  writerBodyRestatesRequest,
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

// ---------------------------------------------------------------------------
// SESSİZ DÜŞÜŞ YASAK — kaynak düzeyi kilit.
//
// Bu katman fail-open'dı: gövde üretimi patlarsa plan olduğu gibi devam ediyor,
// masaüstü yazıcıya verilen kısa brief'i dosyaya AYNEN yazıyordu. Kullanıcı
// "DOCX oluşturuldu" mesajı ve içi konu tarifi olan bir dosya alıyordu —
// üstelik doğrulama da geçiyordu, çünkü kontroller yalnız "dosya var mı"
// diye soruyor. Canlı kanıt: 907dbd2d (21 kelime), b2845b50 (42 kelime).
//
// `fillWriterContent` gerçek model çağrısı yaptığı için davranışsal test
// ağ/zaman aşımına takılıyor; kilit kaynak düzeyinde kuruluyor.
// ---------------------------------------------------------------------------

test("üretilemeyen gövde bildirilir ve plan yayınlanmaz", () => {
  const writer = readFileSync(
    new URL("./writer-content.ts", import.meta.url).pathname.replace(/\/dist\//, "/src/"),
    "utf8",
  );
  assert.ok(writer.includes("unresolved: WriterContentGap[]"), "unresolved bildirilmiyor");

  const materialize = readFileSync(
    new URL("./materialize-plan.ts", import.meta.url).pathname.replace(/\/dist\//, "/src/"),
    "utf8",
  );
  const guard = materialize.indexOf("if (writerContent.unresolved.length > 0)");
  assert.ok(guard > -1, "materializer unresolved'ı okumuyor");
  const body = materialize.slice(guard, guard + 700);
  assert.ok(body.includes("return false"), "plan yayınlanmaya devam ediyor");

  // Plan, adımlar yayınlanmadan ÖNCE tutulmalı: önce kapı, sonra cache.
  const cache = materialize.indexOf("storeDesktopPlanCache", guard);
  assert.ok(cache > guard, "kapı plan cache'inden SONRA geliyor");
});

// ---------------------------------------------------------------------------
// DOĞRULAMA VARLIĞA DEĞİL İÇERİĞE BAKMALI.
//
// Görev doğrulaması yalnız "dosya var mı" diye soruyor:
//   output:artifact ✓  output:file_update ✓  rule:artifact_reference ✓
// Bu yüzden içi konu tarifi olan bir belge tüm kapıları geçiyordu.
// ---------------------------------------------------------------------------

const LIVE_GOAL = "masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet";

test("hedefin kendisi gövde olarak gönderilemez", () => {
  assert.equal(
    writerBodyRestatesRequest({
      step: step({ args: { prompt: LIVE_GOAL } }),
      goalSummary: LIVE_GOAL,
    }),
    true,
  );
});

test("hedefin tarifi de gövde sayılmaz", () => {
  assert.equal(
    writerBodyRestatesRequest({
      step: step({ args: { prompt: `${LIVE_GOAL} document_kind: "report"` } }),
      goalSummary: LIVE_GOAL,
    }),
    true,
  );
});

test("gerçek gövde geçer", () => {
  const body = [
    "Zürafa Bilimsel Raporu",
    "Giriş",
    "Zürafalar Afrika savanlarında yaşayan, uzun boyunlarıyla tanınan memelilerdir.",
    "Beslenme",
    "Ağırlıklı olarak akasya yapraklarıyla beslenirler ve günün büyük bölümünü otlanarak geçirirler.",
  ].join("\n");
  assert.equal(
    writerBodyRestatesRequest({
      step: step({ args: { prompt: body } }),
      goalSummary: LIVE_GOAL,
    }),
    false,
  );
});

test("adım referansı taşıyan gövdeye karışılmaz", () => {
  assert.equal(
    writerBodyRestatesRequest({
      step: step({ args: { prompt: "{{steps.arastirma.output}}" } }),
      goalSummary: LIVE_GOAL,
    }),
    false,
  );
});

test("düzyazı olmayan yazıcı kapsam dışı", () => {
  assert.equal(
    writerBodyRestatesRequest({
      step: step({ capability: "spreadsheet_write", args: { prompt: LIVE_GOAL } }),
      goalSummary: LIVE_GOAL,
    }),
    false,
  );
});
