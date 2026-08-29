import assert from "node:assert/strict";
import test from "node:test";
import { compileOutputContract } from "../../core/understanding/output-contract.js";
import { classifyIntent } from "../../core/understanding/intent-classifier.js";
import {
  deriveKnowledgeNeed,
  resolveKnowledgeEvidenceState,
} from "./knowledge-need.js";

test("self-contained typed table does not start RAG or web retrieval", () => {
  const prompt = "Şu verileri tablo olarak göster: 2021: 10, 2022: 20, 2023: 30";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "none");
  assert.equal(result.contract, "elyan.knowledge_need.v2");
});

test("previous typed result is authoritative unless refresh is explicit", () => {
  const prompt = "Az önce verdiğin tabloda en yüksek yıl hangisi?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({
      message: prompt,
      metadata: { authoritativeSourceReference: "previous_answer" },
    }),
    referenceAvailable: true,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "conversation");
  assert.equal(result.evidenceRequired, true);
});

test("current-user identity questions use memory without public web", () => {
  const prompt = "Ben kimim?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
  });
  assert.equal(result.source, "memory");
});

test("required knowledge stays insufficient when every admitted source is empty", () => {
  const knowledgeNeed = deriveKnowledgeNeed({
    query: "Türkiye'nin en yüksek dağı hangisi?",
    classification: classifyIntent({
      userId: "user_1",
      message: "Türkiye'nin en yüksek dağı hangisi?",
    }),
    outputContract: compileOutputContract({
      message: "Türkiye'nin en yüksek dağı hangisi?",
    }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: true,
    attachmentContextUsed: false,
  });
  assert.equal(
    resolveKnowledgeEvidenceState({
      knowledgeNeed,
      referenceAvailable: false,
      memoryResultCount: 0,
      providerEvidenceSufficient: false,
      retrievalEvidenceState: "insufficient",
      webEvidenceSufficient: false,
    }),
    "insufficient",
  );
});

test("typed provider wins before open web and keeps one fallback", () => {
  const prompt = "Güncel dolar kuru nedir?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: true,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
    providerAvailable: true,
  });
  assert.equal(result.source, "provider");
  assert.equal(result.fallback, "web");
});

test("stable Elyan knowledge uses corpus without opening web", () => {
  const prompt = "Elyan masaüstü ne işe yarar?";
  const result = deriveKnowledgeNeed({
    query: prompt,
    classification: classifyIntent({ userId: "user_1", message: prompt }),
    outputContract: compileOutputContract({ message: prompt }),
    referenceAvailable: false,
    socialTurn: false,
    freshPublicDataRequired: false,
    publicWebExplicitlyRequired: false,
    attachmentContextUsed: false,
    corpusAvailable: true,
  });
  assert.equal(result.source, "corpus");
  assert.equal(result.fallback, "model");
});
