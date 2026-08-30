import assert from "node:assert/strict";
import test from "node:test";
import { parseArtifactIntent } from "./parser.js";
import { hasLocalPrivateDataRequest } from "./utils.js";

/**
 * MASAÜSTÜ/MOBİL AYRIMI ÖLÇÜLDÜ: 11 örnekte 7 YANLIŞ.
 *
 * Ayrım tek bir kelime desenine dayanıyordu ve iki yönde de yanılıyordu.
 * Buradaki testler, ölçülen yanlışlardan DÜZELTİLENLERİ sabitler.
 */

test("a definitional question about files is not a desktop request", () => {
  // Üçü de mobil cihazda cevaplanabilir; masaüstü istemek kullanıcıyı
  // olmayan bir engelin arkasında bırakır.
  for (const prompt of [
    "Downloads klasörü nedir, ne işe yarar?",
    "Yerel dosya sistemi nasıl çalışır anlat",
    "Bu klasör yapısı iyi mi? src/modules altında",
  ]) {
    assert.equal(
      hasLocalPrivateDataRequest(prompt),
      false,
      `tanım sorusu masaüstü istememeli: ${prompt}`,
    );
  }
});

test("a genuine local-data request still routes to desktop", () => {
  for (const prompt of [
    "Bilgisayarımdaki son PDF'i özetle",
    "Masaüstümdeki dosyaları listele",
  ]) {
    assert.equal(
      hasLocalPrivateDataRequest(prompt),
      true,
      `gerçek yerel istek masaüstü istemeli: ${prompt}`,
    );
  }
});

/**
 * EN ZARARLI VAKA: kullanıcı dosyayı AZ ÖNCE yüklemişken "masaüstü lazım"
 * demek. Kelime deseni bir ipucudur, ekin varlığı bir olgudur; olgu yener.
 */
test("an attached file means desktop is not required", () => {
  const withAttachment = parseArtifactIntent({
    userRequest: "Ekteki son pdf'i özetle",
    metadata: { attachmentContextUsed: true },
  });
  assert.equal(withAttachment.requiresDesktopRuntime, false);

  const withoutAttachment = parseArtifactIntent({
    userRequest: "Son pdf'i özetle",
  });
  assert.equal(withoutAttachment.requiresDesktopRuntime, true);
});

/**
 * Ek, TİPLİ yetenek kararını yenmez: dosya sistemine yazmak gibi bir istek
 * ek yüklemekle karşılanamaz.
 */
test("an attachment cannot override a typed desktop capability", () => {
  const intent = parseArtifactIntent({
    userRequest: "Bunu kaydet",
    metadata: { attachmentContextUsed: true },
    understandingEnvelope: {
      required_capabilities: [{ executionSurface: "desktop" }],
    } as never,
  });
  assert.equal(intent.requiresDesktopRuntime, true);
});
