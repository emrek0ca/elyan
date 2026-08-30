import assert from "node:assert/strict";
import test from "node:test";
import { validateAssistantBlockContract } from "./message-blocks.js";

const tableBlock = {
  type: "table",
  columns: ["Özellik", "A", "B"],
  rows: [["Kafein", "Var", "Yok"]],
};

/**
 * UYGULANMAYAN BİR SÖZLEŞME, SÖZLEŞME DEĞİLDİR.
 *
 * `forbidden` politikası hesaplanıyor, ihlali `unrequested_table_block`
 * olarak KAYDEDİLİYOR, sonra ihlal yine de kullanıcıya gönderiliyordu.
 * Adı "yasak", davranışı "kaydedilmiş uyarı"ydı — ve okuyan onun tuttuğunu
 * sanıp o varsayım üstüne kod yazar.
 */
test("a forbidden table policy actually removes the table", () => {
  const result = validateAssistantBlockContract({
    blocks: [tableBlock as never],
    content: "Karşılaştırma aşağıda.",
    mode: "normalize",
    tablePolicy: "forbidden",
  });
  assert.ok(
    !result.blocks.some((block) => block.type === "table"),
    "yasak politikada tablo bloğu kullanıcıya gitmemeli",
  );
  assert.ok(
    result.blockQuality.feedbackSignals.includes("unrequested_table_block"),
    "ihlal yine de modele geri bildirilmeli",
  );
});

/**
 * `explicit_only` altında tablo BİLEREK serbesttir: politika yorumunun kendi
 * ifadesiyle "gerçek çok satırlı veri kümesi gerektirir, YASAK DURUM DEĞİL".
 * Bu testin varlığı, yukarıdaki uygulamanın fazla geniş davranmasını önler.
 */
test("explicit_only still lets a model-chosen table through", () => {
  const result = validateAssistantBlockContract({
    blocks: [tableBlock as never],
    content: "Karşılaştırma aşağıda.",
    mode: "normalize",
    tablePolicy: "explicit_only",
  });
  assert.deepEqual(
    result.blocks.map((block) => block.type),
    ["table"],
  );
});

test("no table policy is not a forbidden policy", () => {
  const result = validateAssistantBlockContract({
    blocks: [tableBlock as never],
    content: "Karşılaştırma aşağıda.",
    mode: "normalize",
  });
  assert.deepEqual(
    result.blocks.map((block) => block.type),
    ["table"],
  );
});
