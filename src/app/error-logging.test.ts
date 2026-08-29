import assert from "node:assert/strict";
import test from "node:test";
import { stdSerializers } from "pino";

/**
 * TEŞHİS EDİLEBİLİRLİK ÇAĞIRANIN KELİME SEÇİMİNE BAĞLI OLAMAZ.
 *
 * `Error.message` ve `Error.stack` enumerable DEĞİLDİR. Pino varsayılan
 * olarak yalnız `err` anahtarına serializer uygular, bu yüzden
 * `logger.warn({ error }, "...")` diyen her çağrı sahaya şunu bırakıyordu:
 *
 *   {"error":{"code":"ERR_DLOPEN_FAILED"},"msg":"semantic compute worker crashed"}
 *
 * Üretimde bu tam olarak yaşandı (2026-08-30): semantik işçi çöktü, elde
 * yalnız kod vardı; hangi kütüphanenin yüklenemediği hiç öğrenilemedi.
 * Aynı logdaki auth hataları TAM görünüyordu çünkü `err` yazılmıştı.
 */
test("an Error survives serialization under the error key, not just err", () => {
  const error = Object.assign(new Error("dlopen failed: libfoo.so not found"), {
    code: "ERR_DLOPEN_FAILED",
  });

  // Çıplak hâli: mesaj ve yığın KAYBOLUR — arızanın kendisi budur.
  assert.deepEqual(JSON.parse(JSON.stringify({ error })), {
    error: { code: "ERR_DLOPEN_FAILED" },
  });

  // Serializer'dan geçince teşhis edilebilir olur.
  const serialized = stdSerializers.err(error) as Record<string, unknown>;
  assert.equal(serialized.message, "dlopen failed: libfoo.so not found");
  assert.equal(serialized.code, "ERR_DLOPEN_FAILED");
  assert.equal(typeof serialized.stack, "string");
});
