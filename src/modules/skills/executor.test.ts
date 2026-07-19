import assert from "node:assert/strict";
import test from "node:test";
import type { ResolvedAttachmentContext } from "../brain/attachment-context.js";
import { getActiveSkillById, resetSkillRegistryForTests } from "./registry.js";
import { executeSkill, resetSkillExecutionCacheForTests } from "./executor.js";

class FakeDb {
  readonly inserted: unknown[] = [];

  insert(table: unknown) {
    const inserted = this.inserted;
    const builder = {
      values(values: Record<string, unknown>) {
        inserted.push({ table, values });
        return builder;
      },
    };
    return builder;
  }
}

const attachmentContext: ResolvedAttachmentContext = {
  used: true,
  source: "request_attachments",
  promptBlock: "Attachment context",
  documentIds: ["doc-1"],
  documents: [
    {
      documentId: "doc-1",
      title: "rapor.pdf",
      mimeType: "application/pdf",
      summary: "Bütçe raporu",
      source: "request",
      chunkCount: 2,
      includedChunkCount: 2,
    },
  ],
  chunks: [
    {
      documentId: "doc-1",
      documentTitle: "rapor.pdf",
      mimeType: "application/pdf",
      chunkId: "doc-1:chunk:1",
      chunkHash: "hash-1",
      content: "Rapor bütçe onayının Haziran ayında yapılacağını söylüyor.",
      pageNumber: 1,
      metadata: {},
    },
    {
      documentId: "doc-1",
      documentTitle: "rapor.pdf",
      mimeType: "application/pdf",
      chunkId: "doc-1:chunk:2",
      chunkHash: "hash-2",
      content: "İkinci bölüm teslim takvimini anlatıyor.",
      pageNumber: 2,
      metadata: {},
    },
  ],
  totalChars: 120,
  chunkCount: 2,
  needsClarification: false,
};

test("executor injects only selected skill instructions into model prompt", async () => {
  resetSkillRegistryForTests();
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_summary");
  assert.ok(skill);
  const prompts: string[] = [];
  const db = new FakeDb();

  const result = await executeSkill({
    app: { db } as never,
    userId: "user-1",
    skill: { ...skill, allowedTools: ["web.search"] },
    skillInput: {
      prompt: "Bu belgeyi özetle",
      attachmentContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_summary",
      confidence: 0.9,
      reason: "summary",
      source: "deterministic",
    },
    modelCall: async (input) => {
      prompts.push(input.prompt);
      return {
        text: JSON.stringify({
          summary: "Bütçe onayı Haziran ayında yapılacak.",
          keyPoints: ["Bütçe onayı Haziran ayında", "Teslim takvimi var"],
          confidence: 0.86,
        }),
        provider: "groq",
        model: "test-model",
        latencyMs: 12,
        promptTokens: 100,
        completionTokens: 20,
        totalTokens: 120,
        metadata: {
          groundingUsed: true,
          documentSourceCount: 1,
          webGroundingUsed: true,
          webSourceCount: 3,
          retrievalResultCount: 2,
          toolResults: [
            {
              tool: "web.search",
              ok: true,
              durationMs: 20,
              output: { resultCount: 3, raw: "must not propagate" },
              args: { query: "private prompt" },
            },
            { tool: "filesystem.read", ok: true },
          ],
        },
      };
    },
  });

  assert.ok(result);
  assert.match(prompts[0], /Selected skill: document_summary@/);
  assert.doesNotMatch(prompts[0], /document_key_points/);
  assert.doesNotMatch(prompts[0], /document_qa/);
  assert.doesNotMatch(prompts[0], /test-model|groq|provider/i);
  assert.equal(result.metadata.skillDisplay.label, "Özetle");
  assert.equal(result.metadata.skillDisplay.status, "used");
  assert.equal(result.metadata.groundingUsed, true);
  assert.equal(result.metadata.documentSourceCount, 1);
  assert.equal(result.metadata.webGroundingUsed, true);
  assert.equal(result.metadata.webSourceCount, 3);
  assert.equal(result.metadata.retrievalResultCount, 2);
  assert.deepEqual(result.metadata.toolCalls, ["web.search"]);
  assert.deepEqual(result.metadata.toolResults, [
    {
      tool: "web.search",
      ok: true,
      durationMs: 20,
      resultCount: 3,
      errorCode: null,
    },
  ]);
  assert.doesNotMatch(JSON.stringify(result.metadata), /private prompt|raw/);
  assert.equal(db.inserted.length, 1);
  assert.equal((db.inserted[0] as { values: Record<string, unknown> }).values.type, "skill_execution");
  assert.equal((db.inserted[0] as { values: Record<string, unknown> }).values.source, "brain_skill");
});

test("executor marks manual hint usage in UI-safe metadata and logs", async () => {
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_qa");
  assert.ok(skill);
  const db = new FakeDb();

  const result = await executeSkill({
    app: { db } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Burada ne yazıyor?",
      attachmentContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_qa",
      confidence: 0.95,
      reason: "manual",
      source: "manual_hint",
    },
    modelCall: async () => ({
      text: JSON.stringify({
        answer: "Belgede bütçe bilgisi var.",
        citedChunks: ["hash-1"],
        confidence: 0.8,
      }),
      provider: "groq",
      model: "test-model",
      latencyMs: 15,
      promptTokens: 100,
      completionTokens: 20,
      totalTokens: 120,
      metadata: {},
    }),
  });

  assert.ok(result);
  assert.equal(result.metadata.manualHintUsed, true);
  assert.deepEqual(result.metadata.skillDisplay, {
    label: "Soru-Cevap",
    source: "manual_hint",
    status: "used",
  });
  const inserted = db.inserted[0] as { values: { metadata: Record<string, unknown> } };
  assert.equal(inserted.values.metadata.manualHintUsed, true);
});

test("executor repairs invalid model JSON once", async () => {
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_qa");
  assert.ok(skill);
  let calls = 0;

  const result = await executeSkill({
    app: { db: new FakeDb() } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Burada ne yazıyor?",
      attachmentContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_qa",
      confidence: 0.82,
      reason: "qa",
      source: "deterministic",
    },
    modelCall: async () => {
      calls += 1;
      return {
        text:
          calls === 1
            ? "cevap: bütçe"
            : JSON.stringify({
                answer: "Belgede bütçe onayının Haziran ayında yapılacağı yazıyor.",
                citedChunks: ["hash-1"],
                confidence: 0.84,
              }),
        provider: "groq",
        model: "test-model",
        latencyMs: 15,
        promptTokens: 100,
        completionTokens: 20,
        totalTokens: 120,
        metadata: {},
      };
    },
  });

  assert.ok(result);
  assert.equal(calls, 2);
  assert.equal(result.metadata.validationStatus, "repaired");
});

test("executor rejects unauthorized tool access", async () => {
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_qa");
  assert.ok(skill);
  const db = new FakeDb();

  const result = await executeSkill({
    app: { db } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Burada ne yazıyor?",
      attachmentContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_qa",
      confidence: 0.82,
      reason: "qa",
      source: "deterministic",
    },
    modelCall: async () => ({
      text: JSON.stringify({
        answer: "Belgede bütçe bilgisi var.",
        citedChunks: ["hash-1"],
        confidence: 0.8,
        toolCalls: ["filesystem.read"],
      }),
      provider: "groq",
      model: "test-model",
      latencyMs: 15,
      promptTokens: 100,
      completionTokens: 20,
      totalTokens: 120,
      metadata: {},
    }),
  });

  assert.equal(result, null);
  const inserted = db.inserted[0] as { values: { metadata: Record<string, unknown> } };
  assert.equal(inserted.values.metadata.errorCode, "unauthorized_tool_call");
});

test("executor bounds selected chunk content and keeps raw private text out of logs", async () => {
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_summary");
  assert.ok(skill);
  const secretTail = "SECRET_PRIVATE_TAIL_SHOULD_NOT_BE_SENT";
  const hugeContext: ResolvedAttachmentContext = {
    ...attachmentContext,
    chunks: [
      {
        ...attachmentContext.chunks[0],
        chunkHash: "huge-hash",
        content: `Başlangıç ${"çok uzun içerik ".repeat(3000)} ${secretTail}`,
      },
    ],
  };
  const db = new FakeDb();
  let prompt = "";

  const result = await executeSkill({
    app: { db } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Bu belgeyi özetle",
      attachmentContext: hugeContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_summary",
      confidence: 0.9,
      reason: "summary",
      source: "deterministic",
    },
    modelCall: async (input) => {
      prompt = input.prompt;
      return {
        text: JSON.stringify({
          summary: "Belge uzun içeriğin özetini içeriyor.",
          keyPoints: ["Uzun içerik bounded olarak işlendi"],
          confidence: 0.8,
        }),
        provider: "groq",
        model: "test-model",
        latencyMs: 8,
        promptTokens: 100,
        completionTokens: 12,
        totalTokens: 112,
        metadata: {},
      };
    },
  });

  assert.ok(result);
  assert.doesNotMatch(prompt, new RegExp(secretTail));
  assert.match(prompt, /"truncated":true/);
  assert.doesNotMatch(
    JSON.stringify(db.inserted.map((entry) => (entry as { values: unknown }).values)),
    new RegExp(secretTail),
  );
  assert.deepEqual(result.metadata.selectedChunkHashes, ["huge-hash"]);
});

test("executor prioritizes explicit page references and typed relevance signals", async () => {
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_qa");
  assert.ok(skill);
  const pageContext: ResolvedAttachmentContext = {
    ...attachmentContext,
    chunks: [
      {
        ...attachmentContext.chunks[0],
        chunkHash: "page-1",
        content: "Birinci sayfa genel giriş bilgisini içeriyor.",
        pageNumber: 1,
      },
      {
        ...attachmentContext.chunks[1],
        chunkHash: "page-3",
        content: "Üçüncü sayfada teslim tarihi 18 Haziran ve sorumlu ekip Finans olarak yazıyor.",
        pageNumber: 3,
      },
    ],
  };
  let prompt = "";

  const result = await executeSkill({
    app: { db: new FakeDb() } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Sayfa 3'te teslim tarihi ne yazıyor?",
      attachmentContext: pageContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_qa",
      confidence: 0.9,
      reason: "qa",
      source: "deterministic",
    },
    modelCall: async (input) => {
      prompt = input.prompt;
      return {
        text: JSON.stringify({
          answer: "Sayfa 3'te teslim tarihi 18 Haziran olarak yazıyor.",
          citedChunks: ["page-3"],
          confidence: 0.9,
        }),
        provider: "groq",
        model: "test-model",
        latencyMs: 9,
        promptTokens: 100,
        completionTokens: 12,
        totalTokens: 112,
        metadata: {},
      };
    },
  });

  assert.ok(result);
  assert.equal(result.metadata.selectedChunkHashes[0], "page-3");
  assert.match(prompt, /"relevanceScore":/);
  assert.match(prompt, /"chunkHash":"page-3"/);
});

test("document summary samples beginning middle and end within one cheap pass", async () => {
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_summary");
  assert.ok(skill);
  const chunks = Array.from({ length: 7 }, (_, index) => ({
    ...attachmentContext.chunks[0],
    chunkId: `doc-1:chunk:${index + 1}`,
    chunkHash: `coverage-${index + 1}`,
    content: `Belgenin ${index + 1}. bölümündeki bilgi.`,
    pageNumber: index + 1,
  }));
  let receivedSchema: Record<string, unknown> | null = null;

  const result = await executeSkill({
    app: { db: new FakeDb() } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Belgenin tamamını özetle",
      attachmentContext: {
        ...attachmentContext,
        documents: [
          {
            ...attachmentContext.documents[0],
            chunkCount: chunks.length,
            includedChunkCount: chunks.length,
          },
        ],
        chunks,
        chunkCount: chunks.length,
      },
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_summary",
      confidence: 0.9,
      reason: "summary",
      source: "deterministic",
    },
    modelCall: async (input) => {
      receivedSchema = input.outputSchema;
      return {
        text: JSON.stringify({
          summary: "Belgenin başlangıç, orta ve sonuç bölümleri özetlendi.",
          keyPoints: ["Temsili bölümler kapsandı"],
          confidence: 0.84,
        }),
        provider: "gemini",
        model: "gemini-fast",
        latencyMs: 8,
        promptTokens: 200,
        completionTokens: 40,
        totalTokens: 240,
        metadata: {},
      };
    },
  });

  assert.ok(result);
  assert.deepEqual(result.metadata.selectedChunkHashes.slice(0, 4), [
    "coverage-1",
    "coverage-3",
    "coverage-5",
    "coverage-7",
  ]);
  assert.deepEqual(receivedSchema, skill.outputSchema);
});

test("executor rejects low-confidence validated outputs", async () => {
  resetSkillExecutionCacheForTests();
  const skill = await getActiveSkillById("document_summary");
  assert.ok(skill);

  const result = await executeSkill({
    app: { db: new FakeDb() } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Bu belgeyi özetle",
      attachmentContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_summary",
      confidence: 0.9,
      reason: "summary",
      source: "deterministic",
    },
    modelCall: async () => ({
      text: JSON.stringify({
        summary: "Belge özeti.",
        keyPoints: ["Bir madde"],
        confidence: 0.1,
      }),
      provider: "groq",
      model: "test-model",
      latencyMs: 8,
      promptTokens: 100,
      completionTokens: 12,
      totalTokens: 112,
      metadata: {},
    }),
  });

  assert.equal(result, null);
});

test("executor honors repairAttempts zero", async () => {
  resetSkillExecutionCacheForTests();
  const baseSkill = await getActiveSkillById("document_qa");
  assert.ok(baseSkill);
  const skill = {
    ...baseSkill,
    validation: {
      ...baseSkill.validation,
      repairAttempts: 0,
    },
  };
  let calls = 0;

  const result = await executeSkill({
    app: { db: new FakeDb() } as never,
    userId: "user-1",
    skill,
    skillInput: {
      prompt: "Burada ne yazıyor?",
      attachmentContext,
    },
    routeDecision: {
      needsSkill: true,
      skillId: "document_qa",
      confidence: 0.82,
      reason: "qa",
      source: "deterministic",
    },
    modelCall: async () => {
      calls += 1;
      return {
        text: "not json",
        provider: "groq",
        model: "test-model",
        latencyMs: 15,
        promptTokens: 100,
        completionTokens: 20,
        totalTokens: 120,
        metadata: {},
      };
    },
  });

  assert.equal(result, null);
  assert.equal(calls, 1);
});
