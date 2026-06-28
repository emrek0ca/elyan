import assert from "node:assert/strict";
import test from "node:test";
import {
  buildAssistantSummaryBlock,
  buildAssistantMessageBlocks,
  composeAssistantMessageBlocks,
  polishAssistantVisibleText,
  sanitizeAssistantVisibleText,
  shapeAssistantMessagePayload,
} from "./message-blocks.js";

test("buildAssistantMessageBlocks keeps text-only answers in a single markdown block", () => {
  const blocks = buildAssistantMessageBlocks(
    "# Başlık\n\nİlk paragraf.\n\nİkinci paragraf.",
  );

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(blocks[0]?.markdown, "# Başlık\n\nİlk paragraf.\n\nİkinci paragraf.");
  assert.equal(blocks[0]?.visibility, "user_visible");
  assert.ok(blocks[0]?.stableBlockId);
  assert.ok(blocks[0]?.cacheDigest);
});

test("buildAssistantMessageBlocks preserves fenced code inside the same markdown block", () => {
  const blocks = buildAssistantMessageBlocks(
    "Önce açıklama.\n\n```ts\nconst a = 1;\nconsole.log(a);\n```\n\nSonra sonuç.",
  );

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(
    blocks[0]?.markdown,
    "Önce açıklama.\n\n```ts\nconst a = 1;\nconsole.log(a);\n```\n\nSonra sonuç.",
  );
});

test("shapeAssistantMessagePayload keeps streaming assistant text in a single running block", () => {
  const payload = shapeAssistantMessagePayload({
    id: "assistant-1",
    role: "assistant",
    status: "running",
    content: "Merhaba\n\nŞunları buldum...",
    metadata: {},
  });
  const blocks = (payload as { blocks?: Array<Record<string, unknown>> }).blocks ?? [];

  assert.equal(payload.id, "assistant-1");
  assert.equal(payload.role, "assistant");
  assert.equal(payload.status, "running");
  assert.equal(payload.content, "Merhaba\n\nŞunları buldum...");
  assert.deepEqual(payload.metadata, {});
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(blocks[0]?.markdown, "Merhaba\n\nŞunları buldum...");
});

test("shapeAssistantMessagePayload merges legacy multi-block metadata into one text block", () => {
  const payload = shapeAssistantMessagePayload({
    id: "assistant-2",
    role: "assistant",
    status: "completed",
    content: "",
    metadata: {
      blocks: [
        {
          type: "text",
          markdown: "İlk paragraf.",
        },
        {
          type: "text",
          markdown: "İkinci paragraf.",
        },
      ],
    },
  });

  const blocks = (payload as { blocks?: Array<Record<string, unknown>> }).blocks ?? [];
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(blocks[0]?.markdown, "İlk paragraf.\n\nİkinci paragraf.");
});

test("composeAssistantMessageBlocks preserves task trace blocks before the text answer", () => {
  const blocks = composeAssistantMessageBlocks({
    content: "Belge hazır.",
    blocks: [
      {
        type: "task_trace",
        taskId: "task-1",
        status: "running",
        title: "Görev yürütülüyor",
        steps: [
          {
            id: "intent",
            label: "Niyet anlaşıldı",
            status: "completed",
          },
        ],
      },
    ],
  });

  assert.equal(blocks.length, 2);
  assert.equal(blocks[0]?.type, "task_trace");
  assert.equal(blocks[1]?.type, "text");
  assert.equal(blocks[1]?.markdown, "Belge hazır.");
});

test("sanitizeAssistantVisibleText strips internal reasoning and keeps the final user-facing answer", () => {
  const sanitized = sanitizeAssistantVisibleText(`
1. Analyze User Input:
- The user says: "Bunda ne var"

Looking at the system prompt: attachment context is available.

Final answer: Bu belge, Osman Emre Koca ve Abdullah için dışarı çıkış izin formu gibi görünüyor.
  `);

  assert.equal(
    sanitized,
    "Bu belge, Osman Emre Koca ve Abdullah için dışarı çıkış izin formu gibi görünüyor.",
  );
});

test("sanitizeAssistantVisibleText replaces provider and prompt disclosure with Elyan product identity", () => {
  const sanitized = sanitizeAssistantVisibleText(
    "Altta Groq üzerinde llama modeli çalışıyor; system prompt bunu gizlememi söylüyor.",
  );

  assert.match(sanitized, /Elyan/);
  assert.doesNotMatch(sanitized, /groq|llama|system prompt|provider|sağlayıcı|iç model/i);
});

test("sanitizeAssistantVisibleText preserves provider names as public web research topics", () => {
  const sanitized = sanitizeAssistantVisibleText(
    "OpenAI resmi blogunda yayımlanan duyuru, GPT ailesindeki güvenlik değerlendirmelerini ve dağıtım yaklaşımını özetliyor.",
    { allowPublicProviderReferences: true },
  );

  assert.match(sanitized, /OpenAI/);
  assert.match(sanitized, /GPT/);
  assert.doesNotMatch(sanitized, /Ben Elyan olarak çalışırım/);
});

test("sanitizeAssistantVisibleText still redacts Elyan implementation provider claims", () => {
  const sanitized = sanitizeAssistantVisibleText(
    "Ben Elyan, OpenAI üzerinde çalışan GPT tabanlı bir modelim.",
    { allowPublicProviderReferences: true },
  );

  assert.match(sanitized, /Elyan/);
  assert.doesNotMatch(sanitized, /OpenAI|GPT tabanlı/i);
});

test("polishAssistantVisibleText replaces protected Elyan provider disclosure", () => {
  const polished = polishAssistantVisibleText(
    "Elyan, Osman Emre Koca tarafından geliştirilen; kullanıcıya yalnızca Elyan olarak sunulur; iç model ve sağlayıcı ayrıntıları güvenlik ve ürün bütünlüğü gereği paylaşılmaz.",
  );

  assert.match(polished, /Elyan/);
  assert.doesNotMatch(polished, /iç model|sağlayıcı|güvenlik ve ürün bütünlüğü/i);
});

test("sanitizeAssistantVisibleText replaces obfuscated provider and prompt leaks", () => {
  const sanitized = sanitizeAssistantVisibleText(
    "G.R.O.Q sağlayıcısı ve s y s t e m prompt ayrıntıları içeren dahili cevap.",
  );

  assert.match(sanitized, /Elyan/);
  assert.doesNotMatch(sanitized, /groq|system prompt|provider|sağlayıcı|dahili/i);
});

test("sanitizeAssistantVisibleText removes think tags and hidden reasoning blocks", () => {
  const sanitized = sanitizeAssistantVisibleText(`
<think>
The user wants me to rate their appearance based on the provided image.
</think>

Final answer: Fotoğrafı burada güvenli şekilde puanlamıyorum, ama istersen stil, ışık ve kompozisyon açısından yorumlayabilirim.
  `);

  assert.equal(
    sanitized,
    "Fotoğrafı burada güvenli şekilde puanlamıyorum, ama istersen stil, ışık ve kompozisyon açısından yorumlayabilirim.",
  );
});

test("sanitizeAssistantVisibleText falls back to extracted OCR text when the reply is only internal analysis", () => {
  const sanitized = sanitizeAssistantVisibleText(`
- User says: "Ne yazıyor burada"
- Language: Turkish
- Attachment context shows:
- OCR/Summary text: "10:03 cku.itiraf.paylasim •II = 37 •.. Saat gece bir buçuk suları yurttan flaş yaktığımız kızlar bizi bulabilirmi"
- Page 1 content: "10:03 cku.itiraf.paylasim •II = 37"
  `);

  assert.equal(
    sanitized,
    "10:03 cku.itiraf.paylasim •II = 37 •.. Saat gece bir buçuk suları yurttan flaş yaktığımız kızlar bizi bulabilirmi",
  );
});

test("polishAssistantVisibleText drops broken trailing fragments without inventing content", () => {
  const polished = polishAssistantVisibleText("Kısa sonuç burada.\n\nDetaylar hazır\n\nve");
  assert.equal(polished, "Kısa sonuç burada.\n\nDetaylar hazır");
});

test("shapeAssistantMessagePayload replaces assistant content with the visible answer", () => {
  const payload = shapeAssistantMessagePayload({
    id: "assistant-3",
    role: "assistant",
    status: "completed",
    content:
      'Analyze User Input\\nThe user says: "Nasılsın"\\n\\nFinal answer: İyiyim, teşekkür ederim!',
    metadata: {},
  });
  const blocks = (payload as { blocks?: Array<Record<string, unknown>> }).blocks ?? [];

  assert.equal(payload.content, "İyiyim, teşekkür ederim!");
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(blocks[0]?.markdown, "İyiyim, teşekkür ederim!");
});

test("composeAssistantMessageBlocks keeps summary before visible text fallback", () => {
  const summary = buildAssistantSummaryBlock("Kısa sonuç hazır.", {
    title: "Sonuç",
  });
  const blocks = composeAssistantMessageBlocks({
    content: "Daha detaylı açıklama burada.",
    blocks: [summary],
  });

  assert.equal(blocks.length, 2);
  assert.equal(blocks[0]?.type, "summary");
  assert.equal(blocks[1]?.type, "text");
});

test("composeAssistantMessageBlocks preserves internal visibility metadata for non-text blocks", () => {
  const blocks = composeAssistantMessageBlocks({
    content: "Kullanıcıya açık cevap.",
    blocks: [
      {
        type: "context_signal",
        title: "Bağlam",
        visibility: "assistant_internal_by_default",
        items: [{ label: "Enerji", value: "Düşük olabilir" }],
      },
    ],
  });

  assert.equal(blocks.length, 2);
  assert.equal(blocks[0]?.type, "context_signal");
  assert.equal(blocks[0]?.visibility, "assistant_internal_by_default");
  assert.equal(blocks[1]?.type, "text");
});

test("sanitizeAssistantVisibleText converts raw br tags into readable markdown lines", () => {
  const sanitized = sanitizeAssistantVisibleText(
    "Sonuç:\n\n| Kategori | Değer |\n|---|---|\n| Eğitim | 1924 Kanunu<br>1928 Harf Devrimi |",
  );

  assert.doesNotMatch(sanitized, /<br>/i);
  assert.match(sanitized, /1924 Kanunu\n1928 Harf Devrimi/);
});

test("composeAssistantMessageBlocks accepts table and file blocks additively", () => {
  const blocks = composeAssistantMessageBlocks({
    content: "Tabloyu özetledim.",
    blocks: [
      {
        type: "file",
        fileName: "/Users/example/Desktop/rapor.pdf",
        mimeType: "application/pdf",
        preview: "Kısa rapor özeti",
      },
      {
        type: "table",
        title: "Özet tablo",
        columns: ["Kategori", "Değer"],
        rows: [["Eğitim", "1924 Kanunu<br>1928 Harf Devrimi"]],
      },
    ],
  });

  assert.equal(blocks.length, 3);
  assert.equal(blocks[0]?.type, "file");
  assert.equal(blocks[0]?.type === "file" ? blocks[0].fileName : "", "rapor.pdf");
  assert.equal(blocks[1]?.type, "table");
  assert.deepEqual(
    blocks[1]?.type === "table" ? blocks[1].rows[0] : [],
    ["Eğitim", "1924 Kanunu 1928 Harf Devrimi"],
  );
  assert.equal(blocks[2]?.type, "text");
});

test("shapeAssistantMessagePayload keeps top-level typed blocks and appends visible text once", () => {
  const payload = shapeAssistantMessagePayload({
    id: "assistant-typed-1",
    role: "assistant",
    status: "completed",
    content: "Belge hazır.",
    blocks: [
      {
        type: "document_block",
        title: "Haftalık Rapor",
        sections: [{ heading: "Özet", content: "Teslim edildi." }],
      },
    ],
  });

  const blocks = (payload as { blocks?: Array<Record<string, unknown>> }).blocks ?? [];
  assert.equal(blocks.length, 2);
  assert.equal(blocks[0]?.type, "document_block");
  assert.equal(blocks[1]?.type, "text");
  assert.equal(blocks[1]?.markdown, "Belge hazır.");
  assert.equal(payload.content, "Belge hazır.");
});

test("shapeAssistantMessagePayload prefers top-level blocks over empty metadata blocks", () => {
  const payload = shapeAssistantMessagePayload({
    id: "assistant-typed-2",
    role: "assistant",
    status: "completed",
    content: "",
    blocks: [
      {
        type: "attachment_ack",
        summary: "1 belge alındı.",
        attachmentCount: 1,
      },
    ],
    metadata: { blocks: [] },
  });

  const blocks = (payload as { blocks?: Array<Record<string, unknown>> }).blocks ?? [];
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "attachment_ack");
  assert.equal((blocks[0] as { summary?: string }).summary, "1 belge alındı.");
});
