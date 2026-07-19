import assert from "node:assert/strict";
import test from "node:test";
import {
  shouldAcceptExtractedTypedBlock,
  tableBlockToPlainFallback,
} from "./typed-block-policy.js";

test("tableBlockToPlainFallback renders a compact readable list", () => {
  assert.equal(
    tableBlockToPlainFallback({
      type: "table",
      title: "**Ülkeler**",
      columns: ["Ülke", "Nüfus", "Yüzölçümü"],
      rows: [
        ["Türkiye", "85M", "783 bin km²"],
        { country: "Almanya", population: "84M", area: "357 bin km²" },
      ],
    }),
    "Ülkeler:\n- Türkiye: Nüfus: 85M; Yüzölçümü: 783 bin km²\n- Almanya: Nüfus: 84M; Yüzölçümü: 357 bin km²",
  );
});

test("shouldAcceptExtractedTypedBlock requires explicit table intent even for a stale table workload", () => {
  assert.equal(
    shouldAcceptExtractedTypedBlock({
      block: { type: "table" },
      prompt: "Bana kısa bir liste ver",
      selectedWorkload: "mobile_chat_fast",
    }),
    false,
  );
  assert.equal(
    shouldAcceptExtractedTypedBlock({
      block: { type: "table" },
      prompt: "Bunu tablo olarak ver",
      selectedWorkload: "mobile_chat_fast",
    }),
    true,
  );
  assert.equal(
    shouldAcceptExtractedTypedBlock({
      block: { type: "table" },
      prompt: "Bana kısa bir liste ver",
      selectedWorkload: "table_generate",
    }),
    false,
  );
  assert.equal(
    shouldAcceptExtractedTypedBlock({
      block: { type: "table" },
      prompt:
        "Exponential backoff’u iki maddede açıkla. Süreler 1, 2 ve 4 saniye olsun, jitter ekle. Tablo kullanma.",
      selectedWorkload: "table_generate",
    }),
    false,
  );
});

test("shouldAcceptExtractedTypedBlock gates document blocks by workload", () => {
  assert.equal(
    shouldAcceptExtractedTypedBlock({
      block: { type: "document_block" },
      prompt: "Rapor hazırla",
      selectedWorkload: "mobile_chat_fast",
    }),
    false,
  );
  assert.equal(
    shouldAcceptExtractedTypedBlock({
      block: { type: "document_block" },
      prompt: "Rapor hazırla",
      selectedWorkload: "document_generate",
    }),
    true,
  );
});
