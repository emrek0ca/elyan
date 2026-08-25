import assert from "node:assert/strict";
import test from "node:test";
import {
  parseLocalListingQuery,
  parseSystemInfoQuery,
} from "./system-observation.js";

test("yerel klasör okuma modelsiz derlenir", () => {
  for (const message of [
    "Masaüstünde hangi klasörler var?",
    "Masaüstündeki klasörleri listele",
    "masaüstümdeki dosyaları göster",
  ]) {
    assert.deepEqual(
      parseLocalListingQuery(message),
      { capability: "directory_tree", root: "~/Desktop" },
      message,
    );
  }
  assert.equal(parseLocalListingQuery("Downloads klasörümde ne var?")?.root, "~/Downloads");
  assert.equal(
    parseLocalListingQuery("Belgelerim klasöründe kaç dosya var")?.root,
    "~/Documents",
  );
});

test("KÖK AÇIKÇA söylenmemişse derlenmez", () => {
  // Belirsizliği tahmin etmektense dinamik yola bırakmak doğrudur.
  assert.equal(parseLocalListingQuery("hangi klasörler var"), null);
  assert.equal(parseLocalListingQuery("dosyaları listele"), null);
});

test("ÜRETİM ve MUTASYON istekleri listeleme şeridine düşmez", () => {
  // Bu şerit yan etkisiz olmalı: tek bir yazma/silme fiili şeridi kapatır.
  for (const message of [
    "Kedilerin yaşamı hakkında araştırma yapıp masaüstüne kaydet",
    "masaüstüne zürafalar hakkında bir pdf hazırla ve kaydet",
    "Masaüstündeki eski dosyaları sil",
    "Masaüstündeki dosyaları Belgeler'e taşı",
    "Masaüstündeki raporu paylaş",
    "Masaüstündeki dosyayı aç",
  ]) {
    assert.equal(parseLocalListingQuery(message), null, message);
  }
});

test("listeleme çapası olmayan cümle derlenmez", () => {
  assert.equal(parseLocalListingQuery("masaüstü arka planını değiştir"), null);
  assert.equal(parseLocalListingQuery(""), null);
  // Uzun, çok bağlamlı cümle tek bir listeleme değildir.
  assert.equal(
    parseLocalListingQuery(
      "masaüstündeki klasörleri göster ve bugünkü takvimimi özetleyip bana bir plan çıkar",
    ),
    null,
  );
});

test("internet bağlantısı sorusu ağ gözlemine derlenir", () => {
  // Ölçüm (2026-08-25): "internete bağlı mıyım" hiç derlenmiyor, dinamik
  // döngüye düşüyordu; desen yalnız "internet bağlantı" biçimini tanıyordu.
  assert.equal(parseSystemInfoQuery("internete bağlı mıyım"), "network");
  assert.equal(parseSystemInfoQuery("internet var mı"), "network");
  assert.equal(parseSystemInfoQuery("wifi bağlı mı"), "network");
});

test("sistem gözlemi şeridi bozulmadı", () => {
  assert.equal(parseSystemInfoQuery("Bilgisayarın şarjı kaç?"), "battery");
  assert.equal(parseSystemInfoQuery("CPU kullanımı nedir"), "cpu");
  assert.equal(parseSystemInfoQuery("saat kaç"), "time");
  assert.equal(
    parseSystemInfoQuery(
      "Bugünkü sağlık, takvim, saat, cihaz durumu ve bildirim bağlamına göre kısa ama tam bir çalışma planı çıkar.",
    ),
    null,
  );
});

test("kimlik bilgisi isteği kapalı gözlem şeridine GİREMEZ", () => {
  // "wifi şifresini göster" ağ terimi + durum ipucu taşıdığı için ağ gözlemine
  // derleniyordu: kullanıcı parola sorup ağ durumu cevabı alır ve istek onay
  // gerektiren kimlik bilgisi yolundan kaçardı.
  assert.equal(parseSystemInfoQuery("wifi şifresini göster"), null);
  assert.equal(parseSystemInfoQuery("wifi parolası nedir"), null);
  assert.equal(parseSystemInfoQuery("keychain şifremi göster"), null);
});

test("ağ terimi tek başına gözlem üretmez", () => {
  // "internetten bir şey indir" de ağ terimi taşır; durum ipucu şart.
  assert.equal(parseSystemInfoQuery("internetten kedi resmi indir"), null);
  assert.equal(parseSystemInfoQuery("internetten araştırma yap"), null);
  assert.equal(parseSystemInfoQuery("ağ ayarlarını değiştir"), null);
});
