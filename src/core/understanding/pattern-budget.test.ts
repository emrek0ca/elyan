import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

/**
 * DESEN BÜTÇESİ — kelime listeleri büyüyemez.
 *
 * Elyan'daki en eski borç: bir niyet yanlış anlaşıldığında çözüm olarak
 * desene bir kelime daha ekleniyor. Her ekleme tek başına makul, toplamı ise
 * bitmeyen bir iş — ve hiç kimse toplamı görmüyor.
 *
 * BU TEST DESENLERİ YASAKLAMIYOR. Deterministik desen katmanı UCUZDUR ve
 * gerçek bir işi var: turun ne istediğini model çağrısı yapmadan kestirmek.
 * Aynı işi modele devretmek her tura bir gidiş-dönüş ekler; bu kod tabanında
 * o maliyet ölçüldü (beceri sınıflandırıcısı: cevabın kendisi kadar, 1481 ms)
 * ve kaldırıldı. Deseni model çağrısıyla değiştirmek o hatayı geri getirir.
 *
 * Yasaklanan şey BÜYÜMEDİR. Bir desen bir turu yanlış okuduğunda refleks
 * "listeye bir kelime daha ekle" olmamalı; doğru soru şu: bu kararı veren
 * yerde KANIT var mı? (Düzenleme için görsel, grafik için sayı, masaüstü için
 * bağlı cihaz.) Kanıt kapısı desenin yerini alır ve liste kısalır.
 *
 * Tavan aşıldığında yapılacak şey bu sayıyı yükseltmek değil, eklenen deseni
 * bir kanıt kapısına çevirmektir. Sayı DÜŞTÜĞÜNDE ise buradaki tavan
 * güncellenmeli — ratchet yalnız aşağı doğru hareket eder.
 */

/**
 * Ölçüm: 2026-08-28, YORUMLAR ÇIKARILARAK. Bu sayılar yalnız AZALABİLİR.
 *
 * İlk sayım yorum düzyazısını da desen sayıyordu ve bu yüzden şişkindi
 * (inference.ts 56 görünüyordu, gerçek sayı 46). Şişkin bir tavan borcu
 * olduğundan küçük gösterir ve kapıyı gevşetir.
 */
const PATTERN_BUDGET: Record<string, number> = {
  "src/modules/brain/inference.ts": 46,
  "src/modules/brain/image-generation.ts": 36,
  "src/modules/brain/chat-heuristics.ts": 48,
  "src/core/understanding/understanding-envelope.ts": 25,
};

/**
 * Türkçe fiil/isim listesi taşıyan desenler. Yapısal desenler (markdown
 * tablosu, URL, JSON sınırı, sayı biçimi) bu sayıma GİRMEZ — onlar dil
 * hakkında bir varsayım yapmaz ve borç değildir.
 */
const TURKISH_WORDLIST = /[çğıöşüÇĞİÖŞÜ]|\|(?:yap|yaz|çiz|göster|oluştur|kaydet|sil|aç|kapat)/;

/**
 * Yorumlar sayıma GİRMEZ.
 *
 * İlk sürüm ham kaynağı tarıyordu ve düzyazıyı desen sanıyordu:
 * `// Widget/structured output sinyalleri: ... chart/table/` satırı bir regex
 * literaline birebir benziyor. Sonuç, bir yorum eklendiğinde ratchet'in
 * kırmızıya dönmesiydi — yani ölçtüğünü iddia ettiği şeyi ölçmüyordu.
 * Bir borç sayacının yanlış saydığı an, sayaç olmaktan çıkar.
 */
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

function countWordlistPatterns(file: string): number {
  const source = stripComments(readFileSync(file, "utf8"));
  const patterns = source.match(/\/[^/ ][^/\n]{10,}\/[gimsuy]*/g) ?? [];
  return patterns.filter((pattern) => TURKISH_WORDLIST.test(pattern)).length;
}

for (const [file, budget] of Object.entries(PATTERN_BUDGET)) {
  test(`word-list patterns in ${file} do not grow`, () => {
    const actual = countWordlistPatterns(file);

    assert.ok(
      actual <= budget,
      `${file}: ${actual} desen var, bütçe ${budget}. ` +
        `Yeni bir kelime deseni eklemek yerine kararın verildiği yere KANIT ` +
        `koşulu koy — düzenleme görsel ister, grafik sayı ister, masaüstü ` +
        `bağlı cihaz ister. Bütçeyi yükseltmek borcu görünmez kılar.`,
    );

    assert.ok(
      actual >= budget - 8,
      `${file}: desen sayısı ${actual}'e düştü (bütçe ${budget}). ` +
        `Bu iyi haber — PATTERN_BUDGET içindeki değeri ${actual} yap ki ` +
        `kazanım kalıcı olsun.`,
    );
  });
}
