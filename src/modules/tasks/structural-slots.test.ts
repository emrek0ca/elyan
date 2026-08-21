import assert from "node:assert/strict";
import test from "node:test";
import { extractStructuralSlots } from "./structural-slots.js";

// ---------------------------------------------------------------------------
// Canlı arıza (2026-08-22): iş emrine giden veri TEK PARÇAYDI —
// `entities: [{type:"topic", value:"<cümlenin tamamı>"}]`. Planlayıcı bu yüzden
// `open_app{app_name:"Safariden youtube"}` gibi çöp argüman üretti. Zarftaki
// `extractEntities` ise yalnızca para tutarı çıkarıyordu.
//
// Buradaki yuvalar bilerek DİLDEN BAĞIMSIZ: sanatçı/uygulama adı gibi anlamsal
// yuvalar burada ÇIKARILMAZ (Türkçe ek tahmini bu projede defalarca öldü).
// ---------------------------------------------------------------------------

function values(message: string, type: string): string[] {
  return extractStructuralSlots(message)
    .filter((slot) => slot.type === type)
    .map((slot) => slot.normalized ?? slot.value);
}

test("clock times are extracted and normalised", () => {
  assert.deepEqual(values("toplantıyı 9:05 e al", "time"), ["09:05"]);
  assert.deepEqual(values("14:30 da hatırlat", "time"), ["14:30"]);
  assert.deepEqual(values("saat 7 de", "time"), []);
});

test("dates are normalised to ISO regardless of writing style", () => {
  assert.deepEqual(values("2026-08-22 için not al", "date"), ["2026-08-22"]);
  assert.deepEqual(values("22.08.2026 tarihli rapor", "date"), ["2026-08-22"]);
  assert.deepEqual(values("5/9/26 randevusu", "date"), ["2026-09-05"]);
});

test("quoted text is captured — it usually carries the real name", () => {
  assert.deepEqual(values('"Karanfil"i çal', "quoted"), ["Karanfil"]);
  assert.deepEqual(values("“Yıllar Sonra” adlı şarkı", "quoted"), ["Yıllar Sonra"]);
});

test("format tokens are recognised only at word boundaries", () => {
  assert.deepEqual(values("raporu pdf yap", "format"), ["pdf"]);
  assert.deepEqual(values("word formatında istiyorum", "format"), ["word"]);
  // Kelime İÇİNDE geçen biçim adı yakalanmamalı.
  assert.deepEqual(values("pdfleyici diye bir şey yok", "format"), []);
});

test("quantities keep their unit", () => {
  assert.deepEqual(values("3 sayfa özet çıkar", "quantity"), ["3 sayfa"]);
  assert.deepEqual(values("15 dakika sonra hatırlat", "quantity"), ["15 dakika"]);
  assert.deepEqual(values("2,5 gb yer aç", "quantity"), ["2.5 gb"]);
});

test("an ordinary sentence yields no slots and never throws", () => {
  assert.deepEqual(extractStructuralSlots("Merhaba nasılsın"), []);
  assert.deepEqual(extractStructuralSlots(""), []);
  assert.deepEqual(extractStructuralSlots("   "), []);
});

test("a real live request now decomposes into more than one part", () => {
  // Bugünkü arızanın cümlesi değil ama sınıfı: tek blob yerine yuvalar.
  const slots = extractStructuralSlots(
    'yarın 14:30 da "Proje Raporu" nu pdf yap ve 3 sayfa özet ekle',
  );
  const types = new Set(slots.map((slot) => slot.type));
  assert.ok(types.has("time"));
  assert.ok(types.has("quoted"));
  assert.ok(types.has("format"));
  assert.ok(types.has("quantity"));
  assert.ok(slots.length >= 4, `beklenen ≥4 yuva, gelen ${slots.length}`);
});
