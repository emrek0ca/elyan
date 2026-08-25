import assert from "node:assert/strict";
import test from "node:test";
import {
  hasLocalDocumentReadIntent,
  localDocumentReadCapabilities,
} from "./local-read-intent.js";

test("yerel belgeyi TÜKETEN istek tanınır", () => {
  // Canlı arıza (görev 6126ee16): bu cümle server_brain + normal_chat olarak
  // yönlendirildi ve "Netleştireyim: tam olarak neyi yapmamı istiyorsun?"
  // cevabı geldi. İstek nettir.
  assert.equal(
    hasLocalDocumentReadIntent("Masaüstünde kediler hakkında bi belge var onu özetle"),
    true,
  );
  assert.equal(hasLocalDocumentReadIntent("masaüstündeki raporu oku"), true);
  assert.equal(hasLocalDocumentReadIntent("Downloads'taki pdf'i özetle"), true);
  assert.equal(hasLocalDocumentReadIntent("belgelerimdeki sunumu incele"), true);
});

test("KONUM olmadan okuma yerel sayılmaz", () => {
  // "şu makaleyi özetle" sunucu işidir; yerel yapan şey konumdur.
  assert.equal(hasLocalDocumentReadIntent("şu makaleyi özetle"), false);
  assert.equal(hasLocalDocumentReadIntent("bu metni oku ve özetle"), false);
});

test("ÜRETİM/KAYDETME niyeti okuma şeridini kapatır", () => {
  // Hem okuyup hem yazan tur, yazma yolunun onay kapılarından geçmeli.
  assert.equal(
    hasLocalDocumentReadIntent("masaüstündeki raporu özetleyip yeni bir dosyaya kaydet"),
    false,
  );
  assert.equal(
    hasLocalDocumentReadIntent("kediler hakkında bir rapor hazırla ve masaüstüne kaydet"),
    false,
  );
  assert.equal(hasLocalDocumentReadIntent("masaüstündeki dosyaları sil"), false);
});

test("dosya adı verilmişse arama adımı gereksizdir", () => {
  assert.deepEqual(
    localDocumentReadCapabilities("masaüstündeki rapor.docx dosyasını özetle"),
    ["document_read"],
  );
  assert.deepEqual(
    localDocumentReadCapabilities("Masaüstünde kediler hakkında bi belge var onu özetle"),
    ["file_search", "document_read"],
  );
});

test("çok uzun cümle dar okuma şeridine girmez", () => {
  assert.equal(
    hasLocalDocumentReadIntent(
      "masaüstündeki raporu oku ve bugünkü takvimimi kontrol edip haftalık planımı gözden geçir ve bana detaylı bir yol haritası anlat lütfen",
    ),
    false,
  );
});
