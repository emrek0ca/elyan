import assert from "node:assert/strict";
import test from "node:test";
import { evaluateSemanticResponseGate } from "./semantic-response-gate.js";

test("semantic gate rejects the live irrelevant document/source fallback in chat", () => {
  const result = evaluateSemanticResponseGate({
    prompt: "İhtiyaçlarımı üç olasılık halinde analiz et",
    text: "Kaynak doğrulaması yapılamadığı için belge oluşturmadım.",
    workload: "mobile_chat_deep_refine",
    blocks: [{ type: "text", blockId: "text-1" }],
  });

  assert.equal(result.accepted, false);
  assert.equal(result.reason, "unsupported_source_or_document_claim");
});
test("semantic gate allows a deep chat reply without turning it into research", () => {
  const result = evaluateSemanticResponseGate({
    prompt: "İhtiyaçlarımı üç olasılık halinde analiz et",
    text: "Üç olasılık görüyorum: dinlenme ihtiyacı, belirsizlik ve öncelik çatışması.",
    workload: "mobile_chat_deep_refine",
    blocks: [{ type: "text", blockId: "text-1" }],
  });

  assert.equal(result.accepted, true);
});

test("semantic gate rejects web and completion claims without evidence", () => {
  assert.equal(
    evaluateSemanticResponseGate({
      prompt: "Bugün haberleri özetle",
      text: "Kaynaklara göre durum tamamlandı.",
      workload: "mobile_chat_balanced",
      blocks: [{ type: "web_search", blockId: "web-1" }],
    }).reason,
    "web_block_without_evidence",
  );
  assert.equal(
    evaluateSemanticResponseGate({
      prompt: "Klasör oluştur",
      text: "Klasör oluşturuldu.",
      workload: "desktop_handoff",
      blocks: [{ type: "status", blockId: "status-1", data: { status: "completed" } }],
    }).reason,
    "completion_claim_without_evidence",
  );
});

test("semantic gate blocks specific facts when required knowledge evidence is missing", () => {
  const result = evaluateSemanticResponseGate({
    prompt: "Türkiye'nin en yüksek dağı hangisi?",
    text: "Ağrı Dağı 5.137 metre ile en yüksek dağdır.",
    workload: "mobile_chat_fast",
    blocks: [{ type: "text", blockId: "text-1" }],
    evidence: { knowledgeEvidenceState: "insufficient" },
  });
  assert.equal(result.accepted, false);
  assert.equal(result.reason, "required_evidence_missing_for_factual_claim");
});

test("semantic gate accepts an honest evidence limitation", () => {
  const result = evaluateSemanticResponseGate({
    prompt: "Türkiye'nin en yüksek dağı hangisi?",
    text: "Bu bilgi için yeterli doğrulanmış kanıt bulamadım.",
    workload: "mobile_chat_fast",
    blocks: [{ type: "text", blockId: "text-1" }],
    evidence: { knowledgeEvidenceState: "insufficient" },
  });
  assert.equal(result.accepted, true);
  assert.equal(result.evidenceState, "insufficient");
});
