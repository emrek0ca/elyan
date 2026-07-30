import assert from "node:assert/strict";
import test from "node:test";
import {
  resolveCompletionAssistantBlocks,
  resolveNonEchoAssistantText,
  resolveVisibleAssistantResponse,
  stripPromptEchoFromAssistantText,
} from "./service.js";

test("resolveCompletionAssistantBlocks promotes markdown tables into typed table blocks", () => {
  const result = resolveCompletionAssistantBlocks({
    prompt: "Durumu tablo olarak ver",
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

test("resolveCompletionAssistantBlocks promotes leading chart math and svg JSON", () => {
  const chart = resolveCompletionAssistantBlocks({
    prompt: "x^2 fonksiyonunun grafiğini çiz",
    responseText:
      '{"type":"chart","chartType":"function","expression":"pow(x,2)","variables":["x"],"range":{"x":[-2,2]}}\nGrafik hazır.',
    assistantBlocks: [],
  });
  const math = resolveCompletionAssistantBlocks({
    prompt: "Bu integrali LaTeX olarak çöz",
    responseText:
      '{"type":"math","content":"\\\\int_0^1 x^2 dx = \\\\frac{1}{3}","format":"latex"}',
    assistantBlocks: [],
  });
  const svg = resolveCompletionAssistantBlocks({
    prompt: "Basit SVG daire çiz",
    responseText:
      '{"type":"svg","svg":"<svg viewBox=\\"0 0 10 10\\"><circle cx=\\"5\\" cy=\\"5\\" r=\\"4\\"/></svg>"}',
    assistantBlocks: [],
  });

  assert.ok((chart.blocks as Array<Record<string, unknown>>).some((b) => b.type === "chart"));
  assert.ok(!chart.text.includes('"type"'));
  assert.equal(chart.text, "Grafik hazır.");
  assert.ok((math.blocks as Array<Record<string, unknown>>).some((b) => b.type === "math"));
  assert.equal(math.text, "");
  assert.ok((svg.blocks as Array<Record<string, unknown>>).some((b) => b.type === "svg"));
  assert.equal(svg.text, "");
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

test("resolveCompletionAssistantBlocks keeps incidental markdown tables as text when the user did not ask for a table", () => {
  const responseText = [
    "Turk matematikcilerinden bazilari:",
    "",
    "| Isim | Alan | Not |",
    "| --- | --- | --- |",
    "| Cahit Arf | Matematik | Arf degismeziyle bilinir |",
    "| Kerim Erim | Matematik | Erken donem akademisyenlerinden |",
  ].join("\n");

  const result = resolveCompletionAssistantBlocks({
    prompt: "Turk matematikcileri kisaca anlat",
    responseText,
    assistantBlocks: [],
  });

  const blocks = result.blocks as Array<Record<string, unknown>>;
  assert.ok(!blocks.some((block) => block.type === "table"));
  assert.equal(result.text, responseText);
});

test("resolveCompletionAssistantBlocks converts unrequested table JSON to a plain list", () => {
  const result = resolveCompletionAssistantBlocks({
    prompt: "Turk matematikcileri kisaca anlat",
    responseText: JSON.stringify({
      type: "table",
      columns: ["Isim", "Detay"],
      rows: [
        ["**Cahit Arf**", "Arf degismezi ve cebir calismalariyla bilinir."],
        ["Kerim Erim", "Turkiye'de modern matematigin oncusu kabul edilir."],
      ],
    }),
    assistantBlocks: [],
  });

  const blocks = result.blocks as Array<Record<string, unknown>>;
  assert.ok(!blocks.some((block) => block.type === "table"));
  assert.equal(
    result.text,
    [
      "- Cahit Arf: Detay: Arf degismezi ve cebir calismalariyla bilinir.",
      "- Kerim Erim: Detay: Turkiye'de modern matematigin oncusu kabul edilir.",
    ].join("\n"),
  );
});

test("resolveCompletionAssistantBlocks strips dangling structured JSON tails", () => {
  const result = resolveCompletionAssistantBlocks({
    prompt: "PDF olarak ver bunu",
    responseText:
      "Rapor hazırlanıyor, birkaç saniye...Bu tablo, iki platformun geliştirme süreçleri,{",
    assistantBlocks: [],
    selectedWorkload: "document_generate",
  });

  assert.equal(
    result.text,
    "Rapor hazırlanıyor, birkaç saniye...Bu tablo, iki platformun geliştirme süreçleri",
  );
  assert.ok(!result.text.includes("{"));
});

test("resolveCompletionAssistantBlocks deduplicates repeated typed blocks", () => {
  const repeatedTable = {
    type: "table",
    columns: ["Yil", "Gelir"],
    rows: [["2025", "120"]],
  };
  const result = resolveCompletionAssistantBlocks({
    prompt: "Veriyi tablo olarak ver",
    assistantBlocks: [repeatedTable, repeatedTable],
    responseText: "",
  });

  const blocks = result.blocks as Array<Record<string, unknown>>;
  assert.equal(blocks.filter((block) => block.type === "table").length, 1);
});

test("stripPromptEchoFromAssistantText removes prompt-only assistant output", () => {
  assert.equal(
    stripPromptEchoFromAssistantText({
      prompt: "Bana çok bilinmeyen en garip hayvan ismini söyle",
      responseText: "Bana çok bilinmeyen en garip hayvan ismini söyle",
    }),
    "",
  );
});

test("resolveNonEchoAssistantText recovers animal-name prompt echoes with a real answer", () => {
  const answer = resolveNonEchoAssistantText({
    prompt: "Bana çok bilinmeyen en garip hayvan ismini söyle",
    responseText: "Bana çok bilinmeyen en garip hayvan ismini söyle",
  });

  assert.match(answer, /Yıldız burunlu köstebek/u);
  assert.doesNotMatch(answer, /^Bana çok bilinmeyen/u);
});

test("resolveNonEchoAssistantText does not expose broken generation fallback prose", () => {
  const answer = resolveNonEchoAssistantText({
    prompt: "Ceza hukuku nedir?",
    responseText: "Ceza hukuku nedir?",
  });

  assert.doesNotMatch(answer, /Yanıtı düzgün üretemedim/u);
  assert.doesNotMatch(answer, /tekrar dene/u);
  assert.equal(answer, "İsteğini aldım; eldeki bağlamla devam ediyorum.");
});
