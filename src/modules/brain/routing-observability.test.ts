import assert from "node:assert/strict";
import test from "node:test";
import { buildBrainDecisionObservation } from "./decision-observability.js";
import { getSemanticEmbeddingHealth } from "./semantic-compute-client.js";

/**
 * "KANIT YETERSİZDİ" TEK BAŞINA HİÇBİR ŞEY SÖYLEMEZ.
 *
 * Kayıt bugüne kadar yalnız `evidenceState`i tutuyordu. O cümle, YANLIŞ
 * katmana gidildiği için mi yoksa DOĞRU katmanda gerçekten veri olmadığı
 * için mi olduğunu ayırt ettirmiyor — ve bu ikisi taban tabana zıt
 * düzeltmeler gerektirir. Karar, kararın gerekçesi ve sonucu artık aynı
 * kayıtta.
 */
test("a routing decision records which layer answered and why", () => {
  const observation = buildBrainDecisionObservation({
    workload: "mobile_chat_balanced",
    route: "shared_brain",
    knowledgeSource: "corpus",
    knowledgeReason: "stable_corpus_selected",
    knowledgeEmbeddingState: "available",
    evidenceState: "verified",
    result: "success",
    durationMs: 420,
  }) as Record<string, unknown>;

  assert.equal(observation.knowledge_source, "corpus");
  assert.equal(observation.knowledge_reason, "stable_corpus_selected");
  assert.equal(observation.knowledge_embedding_state, "available");
  assert.equal(observation.evidence_state, "verified");
});

/**
 * KÖRLEMESİNE ALINMIŞ KARARDAN DERS ÇIKARILMAZ.
 *
 * Gömme işçisi öldüğünde sağlayıcı/korpus seçimi sözcük eşleşmesine düşer ve
 * sistem çalışmaya devam eder — körleşerek. O turun kötü yönlendirmesi
 * yönlendiricinin suçu değildir; bunu ayırt eden alan olmadan öğrenme
 * tarafı yanlış dersi öğrenir.
 */
test("a decision made without embeddings is marked, not silently equal", () => {
  const blind = buildBrainDecisionObservation({
    knowledgeSource: "none",
    knowledgeEmbeddingState: "unavailable",
    evidenceState: "insufficient",
    result: "success",
    durationMs: 100,
  }) as Record<string, unknown>;
  const informed = buildBrainDecisionObservation({
    knowledgeSource: "none",
    knowledgeEmbeddingState: "available",
    evidenceState: "insufficient",
    result: "success",
    durationMs: 100,
  }) as Record<string, unknown>;

  assert.notEqual(
    blind.knowledge_embedding_state,
    informed.knowledge_embedding_state,
  );
});

/**
 * SAĞLIK SİNYALİ, ÖLÇMESİ GEREKEN ŞEYİ ÖLÇMELİ.
 *
 * `embeddingReady` ML worker'ın KALP ATIŞINDAN türetiliyordu. Semantik
 * hesaplama işçisi `ERR_DLOPEN_FAILED` ile ölmüşken rapor "gömme hazır"
 * diyordu. Bozulmanın görünmemesinin sebebi buydu.
 */
test("embedding health comes from the embedding path itself", () => {
  const health = getSemanticEmbeddingHealth();
  assert.equal(typeof health.enabled, "boolean");
  assert.equal(typeof health.cooldownActive, "boolean");
  assert.equal(typeof health.consecutiveFailures, "number");
  assert.equal(typeof health.failedBatches, "number");
});
