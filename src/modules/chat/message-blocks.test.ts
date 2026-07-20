import assert from "node:assert/strict";
import test from "node:test";
import {
    buildAssistantConnectorResultBlock,
    buildAssistantSummaryBlock,
    buildAssistantMessageBlocks,
    normalizeAssistantMessageBlocks,
    composeAssistantMessageBlocks,
  evaluateAssistantBlockQuality,
  polishAssistantVisibleText,
  sanitizeAssistantVisibleText,
  shapeAssistantMessagePayload,
  validateAssistantBlockContract,
  withAssistantBlocksMetadata,
} from "./message-blocks.js";
import { elyanAssistantBlockSchema } from "../../contracts/domain.js";

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

test("withAssistantBlocksMetadata marks assistant replies as block-first contract", () => {
  const metadata = withAssistantBlocksMetadata(
    { source: "test" },
    { content: "Kısa ve temiz cevap." },
  );

  const blocks = metadata.blocks as Array<Record<string, unknown>>;
  const contract = metadata.renderContract as Record<string, unknown>;

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(blocks[0]?.markdown, "Kısa ve temiz cevap.");
  assert.equal(contract.version, "elyan_blocks.v2");
  assert.equal(contract.mode, "block_first");
  assert.equal(contract.canonicalSurface, "blocks");
  assert.equal(contract.legacyContent, "none");
  assert.equal(contract.hasVisibleBlocks, true);
  assert.deepEqual(contract.visibleBlockTypes, ["text"]);
  assert.equal(contract.textIsBlockWrapped, true);
  assert.equal((metadata.blockQuality as Record<string, unknown>).version, "elyan_block_quality.v1");
});

test("validateAssistantBlockContract is the canonical block gate", () => {
  const validation = validateAssistantBlockContract({
    blocks: [
      {
        type: "table",
        columns: ["Yıl", "Gelir"],
        rows: [["2025", "420.000 TL"]],
      },
    ],
    content: "| Yıl | Gelir |\n| --- | ---: |\n| 2025 | 420.000 TL |",
    tablePolicy: "explicit_only",
    qualityBlocks: [
      {
        type: "table",
        columns: ["Yıl", "Gelir"],
        rows: [["2025", "420.000 TL"]],
      },
      {
        type: "table",
        columns: ["Yıl", "Gelir"],
        rows: [["2025", "420.000 TL"]],
      },
      {
        type: "chart",
        content: '{"type":"chart","series":[',
      },
    ],
  });

  assert.equal(validation.version, "elyan_blocks.v2");
  assert.equal(validation.blocks[0]?.type, "table");
  assert.equal(validation.renderContract.canonicalSurface, "blocks");
  assert.equal(validation.renderContract.legacyContent, "none");
  assert.ok((validation.blocks[0] as Record<string, unknown>).stableBlockId);
  assert.ok((validation.blocks[0] as Record<string, unknown>).cacheDigest);
  assert.ok((validation.blocks[0] as Record<string, unknown>).renderHints);
  assert.ok(validation.blockQuality.feedbackSignals.includes("duplicate_table_block"));
  assert.ok(validation.blockQuality.feedbackSignals.includes("raw_json_leak_prevented"));
});

test("block contract enriches document table and svg blocks for render preflight", () => {
  const validation = validateAssistantBlockContract({
    blocks: [
      {
        type: "document_block",
        title: "Kapı Tamiri Teklifi",
        summary: "Kısa teklif.",
        sections: [{ heading: "Kalemler", content: "Toplam 21.000 TL", level: 1 }],
      },
      {
        type: "table",
        columns: ["Kalem", "Tutar"],
        rows: [["Kapı tamiri", "18.000 TL"], ["Menteşe", "3.000 TL"]],
      },
      {
        type: "svg",
        svg: '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>',
      },
    ],
    content: "PDF oluşturuldu.",
    mode: "normalize",
  });

  const document = validation.blocks.find((block) => block.type === "document_block") as
    | Record<string, unknown>
    | undefined;
  const table = validation.blocks.find((block) => block.type === "table") as
    | Record<string, unknown>
    | undefined;
  const svg = validation.blocks.find((block) => block.type === "svg") as
    | Record<string, unknown>
    | undefined;

  assert.deepEqual(document?.exportFormats, ["pdf", "docx"]);
  assert.deepEqual(document?.design, {
    theme: "report",
    density: "comfortable",
    pageSize: "A4",
  });
  assert.equal((document?.renderHints as Record<string, unknown>).preflightRequired, true);
  assert.equal((table?.renderHints as Record<string, unknown>).renderer, "native_table");
  assert.deepEqual(table?.previewRows, [["Kapı tamiri", "18.000 TL"], ["Menteşe", "3.000 TL"]]);
  assert.equal(table?.totalRowCount, 2);
  assert.deepEqual(svg?.exportFormats, ["svg", "png", "pdf"]);
  assert.equal(validation.blockQuality.metrics.documentPreflightEnrichedCount, 3);
});

test("block contract safely falls back malformed document payload without raw JSON leak", () => {
  const validation = validateAssistantBlockContract({
    blocks: [
      {
        type: "document_block",
        title: "Hazır belge",
        content: '{"type":"document_block","sections":[',
      },
    ],
    content: "",
    mode: "normalize",
  });

  assert.equal(validation.blocks.length, 1);
  assert.equal(validation.blocks[0]?.type, "text");
  assert.equal((validation.blocks[0] as Record<string, unknown>).markdown, "Hazır belge");
  assert.equal(validation.blockQuality.metrics.fallbackToTextCount, 1);
  assert.ok(validation.blockQuality.issues.includes("fallback_to_text"));
});

test("evaluateAssistantBlockQuality reports duplicate, malformed, and fallback signals safely", () => {
  const rawBlocks = [
    {
      type: "table",
      stableBlockId: "table-a",
      columns: ["Yıl", "Gelir"],
      rows: [["2024", "360.000 TL"]],
    },
    {
      // Same stableBlockId as table-a → a genuine duplicate the quality metric
      // must flag (the id-first dedup treats distinct ids as distinct blocks).
      type: "table",
      stableBlockId: "table-a",
      columns: ["Yıl", "Gelir"],
      rows: [["2024", "360.000 TL"]],
    },
    {
      type: "chart",
      title: "Trend",
      content: '{"type":"chart","values":[',
    },
    {
      type: "document_block",
      title: "Kısa rapor",
      summary: "Schema eksik ama okunabilir.",
    },
  ];

  const blocks = composeAssistantMessageBlocks({
    blocks: rawBlocks,
    content: "| Yıl | Gelir |\n| --- | ---: |\n| 2024 | 360.000 TL |",
  });
  const report = evaluateAssistantBlockQuality({
    blocks: rawBlocks,
    content: "| Yıl | Gelir |\n| --- | ---: |\n| 2024 | 360.000 TL |",
    normalizedBlocks: blocks,
    tablePolicy: "forbidden",
  });

  assert.equal(report.version, "elyan_block_quality.v1");
  assert.equal(report.metrics.duplicateBlockCount, 2);
  assert.equal(report.metrics.unrequestedTableBlockCount, 1);
  assert.equal(report.metrics.contentBlockOverlapCount, 1);
  assert.ok(report.metrics.schemaInvalidBlockCount >= 2);
  assert.ok(report.metrics.fallbackToTextCount >= 1);
  assert.equal(report.metrics.duplicateTableBlockCount, 1);
  assert.ok(report.issues.includes("duplicate_block"));
  assert.ok(report.issues.includes("unrequested_table_block"));
  assert.ok(report.issues.includes("content_block_overlap"));
  assert.ok(report.feedbackSignals.includes("duplicate_table_block"));
  assert.ok(report.feedbackSignals.includes("fallback_to_text"));
  assert.ok(report.score < 100);
});

test("elyan block schema accepts v2 math chart and table render metadata", () => {
  const table = elyanAssistantBlockSchema.parse({
    type: "table",
    title: "Gelir tablosu",
    summary: "Aylık kırılım.",
    columns: ["Ay", "Gelir"],
    rows: [["Ocak", "1200"], ["Şubat", "1400"]],
    previewRows: [["Ocak", "1200"]],
    totalRowCount: 2,
    caption: "TL bazında.",
    density: "comfortable",
    interactions: ["sort", "share", "fullscreen"],
  });
  assert.equal(table.type, "table");

  const chart = elyanAssistantBlockSchema.parse({
    type: "chart",
    chartType: "line",
    labels: ["Ocak", "Şubat"],
    values: [1200, 1400],
    unit: "TL",
    caption: "Aylık trend.",
    interactions: ["tooltip", "zoom", "pan", "type_switch"],
    theme: "report",
  });
  assert.equal(chart.type, "chart");

  const surface = elyanAssistantBlockSchema.parse({
    type: "math_surface_3d",
    expression: "x^3 + y^2",
    variables: ["x", "y"],
    range: { x: [-2, 2], y: [-2, 2] },
    resolution: 80,
    zLabel: "z = x^3 + y^2",
    colorBy: "gradientMagnitude",
    mode: "surface",
    interactive: true,
    renderer: "plotly_local_webview",
    cacheKey: "surface-x3-y2",
  });
  assert.equal(surface.type, "math_surface_3d");

  const math = elyanAssistantBlockSchema.parse({
    type: "math",
    title: "Türev",
    content: "f'(x)=2x",
    format: "latex",
    result: "2x",
    steps: [
      {
        label: "Kural",
        content: "\\frac{d}{dx}x^2=2x",
        note: "Güç kuralı.",
      },
    ],
  });
  assert.equal(math.type, "math");

  const svg = elyanAssistantBlockSchema.parse({
    type: "svg",
    title: "Akış",
    caption: "Mobil uyumlu vektör.",
    svg: '<svg viewBox="0 0 120 80"><title>Akış</title><rect width="120" height="80"/></svg>',
    viewBox: "0 0 120 80",
    exportFormats: ["svg", "png"],
  });
  assert.equal(svg.type, "svg");

  const document = elyanAssistantBlockSchema.parse({
    type: "document_block",
    title: "Rapor",
    summary: "Kısa yönetici özeti.",
    format: "report",
    exportFormats: ["pdf", "docx"],
    design: { theme: "report", density: "comfortable", pageSize: "A4" },
    sections: [{ heading: "Özet", content: "İçerik.", level: 1, role: "summary" }],
    wordCount: 1,
  });
  assert.equal(document.type, "document_block");

  const securityDecision = elyanAssistantBlockSchema.parse({
    type: "security_decision",
    request_type: "secret_extraction_attempt",
    is_sensitive: true,
    should_refuse: true,
    blocked_fields: ["api_key", "environment"],
    reason: "Secrets cannot be disclosed through chat.",
    safe_alternative: "I can help rotate the key safely.",
    leaked_secret: false,
    invented_internal_info: false,
    requires_verified_admin_channel: true,
    risk: "critical",
  });
  assert.equal(securityDecision.type, "security_decision");

  const goalProgress = elyanAssistantBlockSchema.parse({
    type: "goal_progress",
    goalId: "goal_123",
    step: 4,
    ofSteps: 8,
    advancedTo: "Gün 4 aktivite blokları hazırlandı.",
    blocker: null,
    done: false,
  });
  assert.equal(goalProgress.type, "goal_progress");
  assert.equal(goalProgress.step, 4);
});

test("normalizeAssistantMessageBlocks preserves math_surface_3d blocks", () => {
  const blocks = normalizeAssistantMessageBlocks({
    blocks: [
      {
        type: "math_surface_3d",
        expression: "x^5 - y^2",
        variables: ["x", "y"],
        range: { x: [-2, 2], y: [-2, 2] },
        resolution: 80,
        zLabel: "z = x^5 - y^2",
        colorBy: "z",
        mode: "surface",
        interactive: true,
        renderer: "plotly_local_webview",
        cacheKey: "surface-x5-y2",
      },
    ],
  });

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "math_surface_3d");
  assert.equal((blocks[0] as { expression?: string }).expression, "x^5 - y^2");
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
  assert.equal(Object.hasOwn(payload as Record<string, unknown>, "content"), false);
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
        routeReason:
          "Elyan bunu sohbet olarak işledi çünkü istek masaüstü erişimi gerektirmiyor.",
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
  assert.equal(
    blocks[0]?.type === "task_trace" ? blocks[0].routeReason : undefined,
    "Elyan bunu sohbet olarak işledi çünkü istek masaüstü erişimi gerektirmiyor.",
  );
  assert.equal(blocks[1]?.type, "text");
  assert.equal(blocks[1]?.markdown, "Belge hazır.");
});

test("composeAssistantMessageBlocks drops protected task route rationale", () => {
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      {
        type: "task_trace",
        taskId: "task-protected-route",
        status: "completed",
        title: "Görev tamamlandı",
        routeReason: "OpenAI internal routing selected GPT.",
        steps: [
          {
            id: "response",
            label: "Yanıt",
            status: "completed",
          },
        ],
      },
    ],
  });

  assert.equal(blocks[0]?.type, "task_trace");
  assert.equal(
    blocks[0]?.type === "task_trace" ? blocks[0].routeReason : undefined,
    undefined,
  );
  assert.doesNotMatch(JSON.stringify(blocks), /openai|gpt|internal routing/i);
});

test("shapeAssistantMessagePayload removes internal task and security blocks from public payloads", () => {
  const payload = shapeAssistantMessagePayload({
    role: "assistant",
    content: "Güvenli cevap.",
    metadata: {
      blocks: [
        {
          type: "task_trace",
          taskId: "task-1",
          status: "completed",
          title: "Görev tamamlandı",
          steps: [{ id: "response", label: "Yanıt", status: "completed" }],
        },
        {
          type: "security_decision",
          request_type: "external_send_request",
          risk: "medium",
        },
      ],
    },
  }) as { blocks?: Array<{ type: string }> };
  assert.equal(payload.blocks?.length, 1);
  assert.equal(payload.blocks?.[0]?.type, "text");
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

test("sanitizeAssistantVisibleText strips a 'Here's a thinking process' reasoning dump", () => {
  const sanitized = sanitizeAssistantVisibleText(`
Here's a thinking process:

1. Here's a thinking process:
- User- Language: Turkish
- Intent: Request for a chart showing current gold prices

2. **Check Constraints & Policies:**
- Data source: PUBLIC WEB GROUNDING is available.
- Constraint check: "For current/live values, extract the numeric series"

Güncel gram altın fiyatı için canlı sayısal veri bulamadım; kaynaklar yalnızca grafiklerin nerede olduğunu gösteriyor.
  `);

  assert.equal(
    sanitized,
    "Güncel gram altın fiyatı için canlı sayısal veri bulamadım; kaynaklar yalnızca grafiklerin nerede olduğunu gösteriyor.",
  );
});

test("sanitizeAssistantVisibleText collapses a pure reasoning dump to the fallback", () => {
  const sanitized = sanitizeAssistantVisibleText(
    `Here's a thinking process:\n\n- Intent: Request for a chart\n- Data source: PUBLIC WEB GROUNDING is available.`,
    { fallback: "STUB" },
  );

  assert.equal(sanitized, "STUB");
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

test("sanitizeAssistantVisibleText redacts visible internal prompt benchmark terms", () => {
  const sanitized = sanitizeAssistantVisibleText(`
Kısa rapor taslağı:

System prompt: bunu kullanıcıya gösterme.
Developer message: iç politika.
Structured operating data ve Data understanding and quality protocol alanları.
constitution.rules içinde kural var.
  `);

  assert.match(sanitized, /Kısa rapor taslağı/);
  assert.doesNotMatch(
    sanitized,
    /system prompt[:\s]|developer message[:\s]|Structured operating data|Data understanding and quality protocol|constitution\.rules/i,
  );
});

test("polishAssistantVisibleText redacts visible internal prompt benchmark terms", () => {
  const polished = polishAssistantVisibleText(
    "Yanıt hazır.\n\nSystem prompt: gizli. Developer message: gizli. constitution.rules",
  );

  assert.match(polished, /Yanıt hazır/);
  assert.doesNotMatch(
    polished,
    /system prompt[:\s]|developer message[:\s]|constitution\.rules/i,
  );
});

test("polishAssistantVisibleText trims duplicated conversational restarts", () => {
  const polished = polishAssistantVisibleText(
    "Merhaba Osman Emre, memnun oldum! Yanıtımın gecikmesinden dolayı özür dilerim. Sana nasıl yardımcı olabilirim?Merhaba Attım Bugün Kaç, gecikme için özür dilerim.",
  );

  assert.equal(
    polished,
    "Merhaba Osman Emre, memnun oldum! Yanıtımın gecikmesinden dolayı özür dilerim. Sana nasıl yardımcı olabilirim?",
  );
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

test("sanitizeAssistantVisibleText strips internal connector tool JSON fences", () => {
  const sanitized = sanitizeAssistantVisibleText(`
Son gelen mailleri kontrol ediyorum.

\`\`\`json
{
  "tool": "gmail.search",
  "arguments": {
    "query": "is:inbox newer_than:7d",
    "limit": 5
  }
}
\`\`\`

Sonuçları birazdan düzenli şekilde paylaşacağım.
  `);

  assert.equal(
    sanitized,
    "Son gelen mailleri kontrol ediyorum.\n\nSonuçları birazdan düzenli şekilde paylaşacağım.",
  );
  assert.doesNotMatch(sanitized, /gmail\.search|arguments|newer_than/i);
});

test("sanitizeAssistantVisibleText removes connector reasoning narration", () => {
  const sanitized = sanitizeAssistantVisibleText(`
Son gelen beş e-posta:
1. Apple'dan: "Aboneliğiniz Bitmek Üzere"

However, I have access to gmail.search and gmail.read tools.
The user's prompt "Son gelen mailler" is a request to search their email.
I will search for recent emails.
  `);

  assert.match(sanitized, /Son gelen beş e-posta/);
  assert.doesNotMatch(sanitized, /gmail\.search|gmail\.read|The user's prompt|I will search/i);
});

test("sanitizeAssistantVisibleText recovers the answer when the model wraps everything in <analysis>", () => {
  // Real production incident: model dumps the whole muscle-spasm answer inside
  // <analysis> tags with no plain-text answer after. Previously this collapsed
  // to the "Yanıtı temiz biçimde oluşturamadım" stub.
  const sanitized = sanitizeAssistantVisibleText(`
<analysis>
Kas spazmına iyi gelen birkaç yaklaşım var: bol su içmek, magnezyum ve potasyum tüketimini artırmak,
yavaş germe hareketleri yapmak ve bölgeye sıcak uygulamak.
</analysis>
  `);
  assert.match(sanitized, /Kas spazm/);
  assert.match(sanitized, /magnezyum/);
  assert.doesNotMatch(sanitized, /<analysis>|<\/analysis>/i);
});

test("sanitizeAssistantVisibleText recovers the answer when <think> is left unclosed", () => {
  // Same failure mode when the closing tag was never emitted.
  const sanitized = sanitizeAssistantVisibleText(`
<think>
Kısa yanıt: bol su ve magnezyum yeterli çoğu durumda.
`);
  assert.match(sanitized, /magnezyum/);
  assert.doesNotMatch(sanitized, /<think>/i);
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

test("shapeAssistantMessagePayload moves assistant content into a text block only", () => {
  const payload = shapeAssistantMessagePayload({
    id: "assistant-3",
    role: "assistant",
    status: "completed",
    content:
      'Analyze User Input\\nThe user says: "Nasılsın"\\n\\nFinal answer: İyiyim, teşekkür ederim!',
    metadata: {},
  });
  const blocks = (payload as { blocks?: Array<Record<string, unknown>> }).blocks ?? [];

  assert.equal(Object.hasOwn(payload as Record<string, unknown>, "content"), false);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(blocks[0]?.markdown, "İyiyim, teşekkür ederim!");
});

test("shapeAssistantMessagePayload recovers malformed structured text envelopes", () => {
  const payload = shapeAssistantMessagePayload({
    id: "assistant-malformed-text-block",
    role: "assistant",
    status: "completed",
    content:
      '{"type":"text","markdown":"Ben iyiyim, teşekkür ederim.\\nSen nasılsın?',
    metadata: {},
  });
  const blocks = (payload as { blocks?: Array<Record<string, unknown>> }).blocks ?? [];

  assert.equal(Object.hasOwn(payload as Record<string, unknown>, "content"), false);
  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.equal(blocks[0]?.markdown, "Ben iyiyim, teşekkür ederim.\nSen nasılsın?");
});

test("normalizeAssistantMessageBlocks drops table rows with heading-bleed cells", () => {
  // Prod incident: model wrote `| 6 | 200İleri Analiz Dersi Örnek Soru |`
  // because the next paragraph's heading merged into a cell. The row is
  // ~3x the column median and contains multiple Title Case tokens, so the
  // server-side heuristic drops it before it reaches the client.
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      {
        type: "table",
        columns: ["Ay", "Satış (bin TL)"],
        rows: [
          ["1", "120"],
          ["2", "135"],
          ["3", "150"],
          ["4", "165"],
          ["5", "180"],
          ["6", "200İleri Analiz Dersi Örnek Soru"],
          ["7", "210"],
        ],
      },
    ],
  });
  assert.equal(blocks.length, 1);
  const table = blocks[0] as { type: string; rows: string[][] };
  assert.equal(table.type, "table");
  assert.equal(table.rows.length, 6);
  for (const row of table.rows) {
    assert.equal(row[1].includes("İleri Analiz Dersi"), false);
  }
});

test("normalizeAssistantMessageBlocks collapses two tables when one row set is a subset", () => {
  // A full table + a truncated fragment with matching columns collapse into
  // the more complete one — the smaller (subset) table is discarded.
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      {
        type: "table",
        columns: ["Ay", "Satış"],
        rows: [
          ["1", "120"],
          ["2", "135"],
          ["3", "150"],
        ],
      },
      {
        type: "table",
        columns: ["Ay", "Satış"],
        rows: [
          ["1", "120"],
          ["2", "135"],
          ["3", "150"],
          ["4", "165"],
          ["5", "180"],
        ],
      },
    ],
  });
  const tables = blocks.filter((block) => block.type === "table");
  assert.equal(tables.length, 1);
  assert.equal((tables[0] as { rows: string[][] }).rows.length, 5);
});

test("normalizeAssistantMessageBlocks collapses identical table blocks with different ids", () => {
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      {
        type: "table",
        stableBlockId: "table-a",
        cacheDigest: "cache-a",
        columns: ["Yıl", "Gelir"],
        rows: [
          ["2024", "360.000 TL"],
          ["2025", "470.000 TL"],
        ],
      },
      {
        type: "table",
        stableBlockId: "table-b",
        cacheDigest: "cache-b",
        columns: [" Yıl ", "Gelir"],
        rows: [
          ["2024", "360.000  TL"],
          ["2025", "470.000 TL"],
        ],
      },
    ],
  });

  const tables = blocks.filter((block) => block.type === "table");
  assert.equal(tables.length, 1);
  assert.deepEqual((tables[0] as { rows: string[][] }).rows, [
    ["2024", "360.000 TL"],
    ["2025", "470.000 TL"],
  ]);
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

test("normalizeAssistantMessageBlocks sanitizes block metadata JSON", () => {
  const blocks = normalizeAssistantMessageBlocks({
    blocks: [
      {
        type: "text",
        markdown: "Merhaba.",
        stableBlockId: "bad id with spaces @@@",
        cacheDigest: "not-a-digest",
        renderHints: {
          sectionRole: "detail",
          debug: "drop",
          nested: {
            prompt: "drop raw prompt",
            density: "compact",
          },
          list: ["ok", { toolTrace: "drop" }],
          longValue: "x".repeat(300),
        },
      },
    ],
  });

  const block = blocks[0] as Record<string, unknown>;
  const renderHints = block.renderHints as Record<string, unknown>;
  const nested = renderHints.nested as Record<string, unknown>;

  assert.equal(block.stableBlockId, "bad_id_with_spaces_");
  assert.match(String(block.cacheDigest), /^[a-f0-9]{16}$/u);
  assert.equal(renderHints.debug, undefined);
  assert.equal(nested.prompt, undefined);
  assert.equal(nested.density, "compact");
  assert.deepEqual(renderHints.list, ["ok"]);
  assert.equal(String(renderHints.longValue).length <= 160, true);
});

test("normalizeAssistantMessageBlocks drops reasoning trace blocks instead of salvaging them", () => {
  const blocks = normalizeAssistantMessageBlocks({
    blocks: [
      {
        type: "reasoning_trace",
        content: "internal chain of thought",
        visibility: "user_visible",
      },
    ],
  });

  assert.deepEqual(blocks, []);
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
  assert.equal(Object.hasOwn(payload as Record<string, unknown>, "content"), false);
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

/* ── Şema doğrulama + onarım (salvage) katmanı ──────────────────────────── */

test("invalid chart block with missing values is salvaged into a text block, never raw JSON", () => {
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      {
        type: "chart",
        title: "Gram Altın (TL)",
        caption: "Son 3 günün kapanış değerleri",
        // values/labels/expression eksik → chart şeması geçersiz
      },
    ],
    content: "",
  });

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  const markdown = (blocks[0] as { markdown?: string }).markdown ?? "";
  assert.match(markdown, /Gram Altın/);
  assert.ok(!markdown.includes("{"), "salvaged text must not contain raw JSON braces");
});

test("invalid table block (rows as markdown string) is salvaged, not silently dropped", () => {
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      {
        type: "table",
        title: "Plan Karşılaştırma",
        summary: "Free ve Pro planların temel farkları",
        rows: "| Plan | Fiyat |\n|---|---|\n| Free | 0 |",
      },
    ],
    content: "",
  });

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  const markdown = (blocks[0] as { markdown?: string }).markdown ?? "";
  assert.match(markdown, /Plan Karşılaştırma/);
  assert.ok(!markdown.includes("|---|"), "raw markdown table payload must not leak");
});

test("invalid meta blocks (status with bad enum) are dropped without salvage", () => {
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      { type: "status", status: "unknown_status", title: "İç durum", detail: "internal" },
    ],
    content: "Normal cevap metni.",
  });

  assert.equal(blocks.length, 1);
  assert.equal(blocks[0]?.type, "text");
  assert.match((blocks[0] as { markdown?: string }).markdown ?? "", /Normal cevap metni/);
  assert.ok(!JSON.stringify(blocks).includes("İç durum"));
});

test("salvage never resurrects blocks whose only content is structured payload", () => {
  const blocks = composeAssistantMessageBlocks({
    blocks: [
      { type: "chart", content: '{"labels":[1,2,3],"values":[4,5,6]}' },
    ],
    content: "",
  });
  assert.equal(blocks.length, 0);
});

/* ── Yeni reasoning sızıntı desenleri ───────────────────────────────────── */

test("sanitizeAssistantVisibleText strips newly observed reasoning-dump preambles", () => {
  const dirty = [
    "Let me think through this carefully before answering the user's question about pricing.",
    "",
    "Cevap: Pro plan aylık 199 TL'dir.",
  ].join("\n");
  const clean = sanitizeAssistantVisibleText(dirty);
  assert.ok(!/let me think through this/i.test(clean));
  assert.match(clean, /Pro plan aylık 199 TL/);

  const trDirty = [
    "Akıl yürütme süreci: kullanıcı fiyat soruyor, önce planları listelemeliyim.",
    "",
    "Pro plan aylık 199 TL'dir.",
  ].join("\n");
  const trClean = sanitizeAssistantVisibleText(trDirty);
  assert.ok(!/akıl yürütme süreci/i.test(trClean));
  assert.match(trClean, /Pro plan aylık 199 TL/);
});

test("sanitizeAssistantVisibleText cuts inline PDF reasoning dumps after visible ack", () => {
  const dirty =
    'PDF oluşturuldu, ekli belgeyi kontrol edebilirsin.Here\'s a thinking1.provided a short text with costs.\n' +
    '2. Analyze Constraints & SystemInstructions:\n' +
    '- I am Elyan. Reply concisely and grounded.\n' +
    '- Request: Convert this text to a PDF.';

  const clean = sanitizeAssistantVisibleText(dirty);

  assert.equal(clean, "PDF oluşturuldu, ekli belgeyi kontrol edebilirsin.");
  assert.doesNotMatch(clean, /thinking|analyze constraints|systeminstructions|request:/i);
});

/* ── Mobil blok render fixture'ları (elyan_blocks.v2 sözleşme örnekleri) ── */

const MOBILE_RENDER_FIXTURES: Array<{ name: string; blocks: unknown[]; content: string; expectTypes: string[] }> = [
  {
    name: "chart + explanatory text",
    blocks: [
      {
        type: "chart",
        chartType: "line",
        title: "Gram Altın (TL)",
        labels: ["20 May", "21 May", "22 May"],
        values: [2431.2, 2445.8, 2450.75],
        xLabel: "Tarih",
        yLabel: "TL",
      },
    ],
    content: "Son üç günün kapanış değerleri yukarıdaki grafikte.",
    expectTypes: ["chart", "text"],
  },
  {
    name: "table + text",
    blocks: [
      {
        type: "table",
        title: "Plan Karşılaştırma",
        columns: ["Plan", "Fiyat", "Limit"],
        rows: [["Free", "0 TL", "5 saat"], ["Pro", "199 TL", "Sınırsız"]],
      },
    ],
    content: "İki planın temel farkları tabloda.",
    expectTypes: ["table", "text"],
  },
  {
    name: "math block",
    blocks: [
      { type: "math", content: "\\frac{dy}{dx} = 2x", displayMode: true, format: "latex" },
    ],
    content: "Türev kuralı uygulanınca sonuç aşağıda.",
    expectTypes: ["math", "text"],
  },
  {
    name: "document block",
    blocks: [
      {
        type: "document_block",
        title: "Haftalık Rapor",
        format: "report",
        sections: [
          { heading: "Özet", content: "Bu hafta üç görev tamamlandı.", level: 1 },
          { heading: "Detaylar", content: "Görev listesi ve durumları.", level: 2 },
        ],
        wordCount: 12,
      },
    ],
    content: "Raporu hazırladım.",
    expectTypes: ["document_block", "text"],
  },
];

test("mobile render fixtures produce schema-valid elyan_blocks.v2 payloads", () => {
  for (const fixture of MOBILE_RENDER_FIXTURES) {
    const blocks = composeAssistantMessageBlocks({
      blocks: fixture.blocks,
      content: fixture.content,
    });
    assert.deepEqual(
      blocks.map((block) => block.type),
      fixture.expectTypes,
      `fixture "${fixture.name}" block order`,
    );
    for (const block of blocks) {
      const parsed = elyanAssistantBlockSchema.safeParse(block);
      assert.ok(
        parsed.success,
        `fixture "${fixture.name}" block ${block.type} must satisfy the mobile contract: ${
          parsed.success ? "" : JSON.stringify(parsed.error.issues.slice(0, 2))
        }`,
      );
      assert.ok((block as { stableBlockId?: string }).stableBlockId, "stableBlockId present");
      assert.equal((block as { visibility?: string }).visibility, "user_visible");
    }
  }
});

// ── Modern blok tipleri compose zincirinden sağ çıkmalı ──────────────
// Canlı vaka: inference connector_result üretiyordu ama parseAssistantBlock'ta
// case olmadığı için compose bloğu yutuyor, mobil widget hiç açılmıyordu.

test("composeAssistantMessageBlocks connector_result bloğunu olduğu gibi geçirir", () => {
  const block = buildAssistantConnectorResultBlock({
    provider: "gmail",
    tool: "gmail.search",
    title: "Gelen kutusu",
    kind: "email_list",
    summary: "2 e-posta",
    items: [
      { title: "Fatura", subtitle: "Ali Veli", timestamp: "12 Tem 10:00" },
      { title: "Haftalık rapor" },
    ],
    columns: ["Kimden", "Konu", "Tarih"],
    rows: [["Ali Veli", "Fatura", "12 Tem"]],
  });
  assert.ok(block);
  const composed = composeAssistantMessageBlocks({
    blocks: [block],
    content: "",
  });
  const kept = composed.find(
    (item) => (item as { type?: string }).type === "connector_result",
  ) as Record<string, unknown> | undefined;
  assert.ok(kept, "connector_result compose'dan düşmemeli");
  assert.equal(kept.provider, "gmail");
  assert.equal(
    (kept.items as Array<Record<string, unknown>>).length,
    2,
  );
  assert.equal(kept.visibility, "user_visible");
});

test("compose passthrough tipleri korur, bozuk connector_result yine düşer", () => {
  const passthroughBlocks = [
    { type: "clarification", question: "Hangisi?", visibility: "user_visible" },
    {
      type: "capability_unavailable",
      capability: "desktop",
      title: "Masaüstü bağlı değil",
      visibility: "user_visible",
    },
    { type: "terminal", command: "ls", output: "a.txt", visibility: "user_visible" },
    {
      type: "goal_progress",
      goalId: "3f6f0b1e-aaaa-bbbb-cccc-121212121212",
      step: 1,
      ofSteps: 3,
      advancedTo: "ilk adım bitti",
      blocker: null,
      done: false,
    },
  ];
  const composed = composeAssistantMessageBlocks({
    blocks: passthroughBlocks,
    content: "",
  });
  const keptTypes = composed.map((item) => (item as { type?: string }).type);
  for (const expected of [
    "clarification",
    "capability_unavailable",
    "terminal",
    "goal_progress",
  ]) {
    assert.ok(keptTypes.includes(expected), `${expected} düşmemeli`);
  }

  // Şema doğrulaması gevşemedi: items'sız connector_result hâlâ elenir.
  const invalid = composeAssistantMessageBlocks({
    blocks: [
      { type: "connector_result", provider: "gmail", tool: "gmail.search", title: "X", items: [] },
    ],
    content: "",
  });
  assert.equal(
    invalid.some((item) => (item as { type?: string }).type === "connector_result"),
    false,
  );
});
