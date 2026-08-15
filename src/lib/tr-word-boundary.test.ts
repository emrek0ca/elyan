import assert from "node:assert/strict";
import test from "node:test";
import { trStemPattern, unicodeWordPattern } from "./tr-word-boundary.js";

test("unicodeWordPattern Türkçe harfle BAŞLAYAN kelimeyi yakalar", () => {
  // PRODÜKSİYON VAKASI: "görsel üret" isteği düşüyordu, çünkü JS'de `\b`
  // ASCII `\w` tabanlı ve 'ü' kelime karakteri sayılmıyor.
  assert.equal(/\büret\b/i.test("görsel üret"), false, "eski (bozuk) davranış");
  assert.equal(
    unicodeWordPattern(String.raw`\büret\b`, "i").test("görsel üret"),
    true,
  );
});

test("trStemPattern Türkçe ekleri yakalar, ek toleransı sınırlı kalır", () => {
  const belge = trStemPattern(
    ["rapor", "belge", "doküman", "sözleşme", "word", "docx"],
    { exclude: ["belgesel"] },
  );
  // `\brapor\b` bunları KAÇIRIYORDU — ek gelince sağ sınır oluşmuyor.
  for (const text of [
    "raporunu word belgesi yap",
    "dokümanı çıkar",
    "sözleşmeyi hazırla",
    "bunu docx yap",
  ]) {
    assert.equal(belge.test(text), true, `eşleşmeliydi: ${text}`);
  }
  // Tolerans sınırsız olsaydı "belgesel" de yakalanırdı — belgesel bir film
  // türü, belge isteği değil.
  assert.equal(belge.test("bana güzel bir belgesel öner"), false);
});

test("trStemPattern ek toleransını kısa köklerde kapatır", () => {
  // "ac" (2 harf) ek toleransıyla aranırsa "açıkla", "acele", "acaba"
  // yakalanır — ölçülmüş tuzak, o yüzden tolerans otomatik kapanıyor.
  const ac = trStemPattern(["aç", "ac"]);
  assert.equal(ac.test("chrome'u aç"), true);
  for (const text of ["bunu açıkla", "acele et", "acaba nasıl"]) {
    assert.equal(ac.test(text), false, `eşleşmemeliydi: ${text}`);
  }
});

test("trStemPattern `\\b` tuzağının HER İKİ yönünü de düzeltir", () => {
  const masa = trStemPattern(["masaüstü", "bilgisayar"]);
  // Eski `\bmasaüstü\b` "masaüstümde"yi YANLIŞLIKLA eşleştiriyordu (ASCII
  // `\b` için 'ü'→'m' geçişi sınır gibi görünür) ama "bilgisayarımda"yı hiç
  // yakalamıyordu. İkisi de artık doğru.
  assert.equal(masa.test("masaüstümde kedi çiz"), true);
  assert.equal(masa.test("bilgisayarımda aç"), true);
  assert.equal(masa.test("merhaba nasılsın"), false);
});
