import assert from "node:assert/strict";
import test from "node:test";
import {
  resolveCompletionAssistantBlocks,
  resolveVisibleAssistantResponse,
} from "./service.js";

test("resolveCompletionAssistantBlocks promotes markdown tables into typed table blocks", () => {
  const result = resolveCompletionAssistantBlocks({
    responseText: [
      "Asagidaki tablo durumu gosterir.",
      "",
      "| Isim | Durum | Not |",
      "| --- | --- | --- |",
      "| Ali | Tamamlandi | Onaylandi |",
      "| Ayse | Bekliyor | Inceleme suruyor |",
    ].join("\n"),
    assistantBlocks: [],
  });

  const tableBlock = (result.blocks as Array<Record<string, unknown>>).find(
    (block) => block.type === "table",
  );
  assert.ok(tableBlock);
  assert.deepEqual(tableBlock?.columns, ["Isim", "Durum", "Not"]);
  assert.deepEqual((tableBlock?.rows as string[][] | undefined)?.[0], ["Ali", "Tamamlandi", "Onaylandi"]);
  // The markdown table source must be stripped from the visible text so the
  // table widget is not duplicated as inline markdown.
  assert.ok(!result.text.includes("|"), `text still contains pipes: ${result.text}`);
  assert.ok(result.text.includes("Asagidaki tablo"));
});

test("resolveCompletionAssistantBlocks promotes a leading status JSON and keeps trailing prose", () => {
  // Exact prod regression: model emits status block + reply in one turn. The
  // raw JSON used to leak into chat because the old extractor required the
  // whole response to be a single JSON object.
  const responseText =
    '{"type":"status","status":"needs_desktop","title":"Masaüstü dosyalarını listele",' +
    '"detail":"Masaüstünüzdeki dosya ve klasörleri tarayıp bir liste oluşturacak."}\n' +
    "Masaüstünüzdeki dosya ve klasörlerin bir listesini oluşturmak için masaüstü uygulamasını çalıştıracağım.";

  const result = resolveCompletionAssistantBlocks({
    responseText,
    assistantBlocks: [],
  });

  const blocks = result.blocks as Array<Record<string, unknown>>;
  const statusBlock = blocks.find((b) => b.type === "status");
  assert.ok(statusBlock, "status block was not promoted");
  assert.equal(statusBlock?.status, "needs_desktop");
  // The raw JSON must NOT appear in visible text.
  assert.ok(!result.text.includes('"type"'), `raw JSON leaked: ${result.text}`);
  assert.ok(!result.text.includes("needs_desktop"));
  // The model's trailing prose must be preserved verbatim.
  assert.ok(result.text.startsWith("Masaüstünüzdeki dosya"));
});

test("resolveCompletionAssistantBlocks handles a bare-only typed JSON response", () => {
  const result = resolveCompletionAssistantBlocks({
    responseText:
      '{"type":"status","status":"needs_desktop","title":"x","detail":"y"}',
    assistantBlocks: [],
  });

  const blocks = result.blocks as Array<Record<string, unknown>>;
  assert.ok(blocks.some((b) => b.type === "status"));
  assert.equal(result.text.trim(), "");
});

test("resolveCompletionAssistantBlocks ignores prose that merely contains a JSON-looking phrase", () => {
  // Negative case: the response is plain prose with a JSON snippet quoted in
  // the middle. Nothing should be promoted; the text must pass through intact.
  const responseText =
    'Plan şöyle: önce {"type":"status"} formatında bir blok döneceğim, sonra cevap.';

  const result = resolveCompletionAssistantBlocks({
    responseText,
    assistantBlocks: [],
  });

  const blocks = result.blocks as Array<Record<string, unknown>>;
  assert.ok(!blocks.some((b) => b.type === "status"));
  assert.equal(result.text, responseText);
});

test("resolveVisibleAssistantResponse avoids fallback error text when structured blocks already exist", () => {
  const visibleText = resolveVisibleAssistantResponse({
    responseText: "",
    assistantBlocks: [
      {
        type: "document_block",
        title: "Haftalik Rapor",
        sections: [{ heading: "Ozet", content: "Teslim edildi." }],
      },
    ],
  });

  assert.equal(visibleText, "");
});
