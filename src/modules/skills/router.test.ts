import assert from "node:assert/strict";
import test from "node:test";
import type { ResolvedAttachmentContext } from "../brain/attachment-context.js";
import { listActiveSkillSummaries, resetSkillRegistryForTests } from "./registry.js";
import { routeSkill } from "./router.js";

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
      summary: "Rapor özeti",
      source: "request",
      chunkCount: 1,
      includedChunkCount: 1,
    },
  ],
  chunks: [
    {
      documentId: "doc-1",
      documentTitle: "rapor.pdf",
      mimeType: "application/pdf",
      chunkId: "doc-1:chunk:1",
      chunkHash: "hash-1",
      content: "Rapor bütçe ve teslim tarihlerini anlatıyor.",
      pageNumber: 1,
      metadata: {},
    },
  ],
  totalChars: 48,
  chunkCount: 1,
  needsClarification: false,
};

test("router selects document_summary for summary requests", async () => {
  resetSkillRegistryForTests();
  const decision = await routeSkill({
    prompt: "Bu belgeyi özetle",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_summary");
});

test("router honors a valid manual skill hint before deterministic routing", async () => {
  const decision = await routeSkill({
    prompt: "Bu belgeyi özetle",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
    skillHint: "document_qa",
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_qa");
  assert.equal(decision.source, "manual_hint");
});

test("router ignores invalid manual skill hints and falls back to deterministic routing", async () => {
  const decision = await routeSkill({
    prompt: "Bu belgeyi özetle",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
    skillHint: "unknown_skill",
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_summary");
  assert.notEqual(decision.source, "manual_hint");
});

test("router does not force a hinted attachment skill without attachment context", async () => {
  const decision = await routeSkill({
    prompt: "Selam",
    attachmentContext: {
      ...attachmentContext,
      used: false,
      chunks: [],
    },
    skills: await listActiveSkillSummaries(),
    skillHint: "document_summary",
  });

  assert.equal(decision.needsSkill, false);
  assert.equal(decision.source, "fallback");
});

test("router selects document_key_points for key point extraction", async () => {
  const decision = await routeSkill({
    prompt: "Önemli noktalar ve aksiyonları çıkar",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_key_points");
});

test("router selects document_qa for document questions", async () => {
  const decision = await routeSkill({
    prompt: "Burada ne yazıyor?",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_qa");
});

test("router falls back when confidence is low", async () => {
  const decision = await routeSkill({
    prompt: "bunu değerlendir",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
    classify: async () => ({
      needsSkill: true,
      skillId: "document_summary",
      confidence: 0.4,
      reason: "low confidence",
      source: "classifier",
    }),
  });

  assert.equal(decision.needsSkill, false);
});

test("router selects document_qa for 'burada ne yazıyor' without question mark", async () => {
  const decision = await routeSkill({
    prompt: "Burada ne yazıyor",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_qa");
});

test("router selects document_qa for 'bunda ne var'", async () => {
  const decision = await routeSkill({
    prompt: "Bunda ne var",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_qa");
});

test("router selects document_qa for image attachment with OCR question", async () => {
  const imageContext: ResolvedAttachmentContext = {
    ...attachmentContext,
    documents: [
      {
        documentId: "img-1",
        title: "screenshot.png",
        mimeType: "image/png",
        summary: "Görsel özeti",
        source: "request",
        chunkCount: 1,
        includedChunkCount: 1,
      },
    ],
    chunks: [
      {
        documentId: "img-1",
        documentTitle: "screenshot.png",
        mimeType: "image/png",
        chunkId: "img-1:chunk:1",
        chunkHash: "img-hash-1",
        content: "OCR çıktısı: Toplantı notu 15 Haziran",
        pageNumber: 1,
        metadata: {},
      },
    ],
  };

  const decision = await routeSkill({
    prompt: "Bu görselde ne yazıyor",
    attachmentContext: imageContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_qa");
});

test("router selects document_key_points for decision/date extraction", async () => {
  const decision = await routeSkill({
    prompt: "Belgedeki kararlar ve tarihler neler?",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_key_points");
});

test("router selects document_summary for 'özetini çıkar'", async () => {
  const decision = await routeSkill({
    prompt: "Bu raporun özetini çıkar",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_summary");
});

test("router falls back when no attachment context used", async () => {
  const unusedContext: ResolvedAttachmentContext = {
    ...attachmentContext,
    used: false,
    chunks: [],
  };

  const decision = await routeSkill({
    prompt: "Bu belgeyi özetle",
    attachmentContext: unusedContext,
    skills: await listActiveSkillSummaries(),
  });

  assert.equal(decision.needsSkill, false);
  assert.equal(decision.source, "fallback");
});

test("router uses classifier when deterministic routing does not match", async () => {
  let classifierCalled = false;
  const decision = await routeSkill({
    prompt: "bunu daha anlaşılır yap",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
    classify: async () => {
      classifierCalled = true;
      return {
        needsSkill: true,
        skillId: "document_qa",
        confidence: 0.75,
        reason: "classifier selected qa",
        source: "classifier",
      };
    },
  });

  assert.equal(classifierCalled, true);
  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_qa");
});

test("router leaves unsupported Excel generation to the artifact pipeline", async () => {
  const decision = await routeSkill({
    prompt: "Bu belgedeki satırları Excel dosyasına çevir",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
    desiredOutputKinds: ["xlsx", "table"],
  });

  assert.equal(decision.needsSkill, false);
  assert.match(decision.reason, /produces every explicitly requested output/i);
});

test("router allows document summary skill when PDF export is explicitly requested", async () => {
  const decision = await routeSkill({
    prompt: "Bu belgeyi özetle ve PDF olarak hazırla",
    attachmentContext,
    skills: await listActiveSkillSummaries(),
    desiredOutputKinds: ["pdf"],
  });

  assert.equal(decision.needsSkill, true);
  assert.equal(decision.skillId, "document_summary");
});
