import assert from "node:assert/strict";
import test from "node:test";
import {
  applyClaimConfidenceMetadata,
  buildClaimConfidenceMetadata,
  buildClaimLedger,
  buildClaimConfidencePromptDirective,
} from "./claim-confidence.js";

test("buildClaimLedger lowers confidence for contested memory", () => {
  const ledger = buildClaimLedger({
    route: "shared_brain",
    workload: "mobile_chat_fast",
    understandingContext: {
      clarificationDiagnostics: { shouldClarify: false },
      retrievedMemory: [
        {
          id: "mem_1",
          type: "identity",
          key: "preferred_name",
          value: "private value must not be copied",
          confidence: 94,
          scope: "user",
          source: "test",
          createdAt: new Date("2026-07-01T00:00:00.000Z"),
          staleness: "contested",
          conflictStatus: "contested",
        },
      ],
      cognitiveContext: {
        uncertainty: {
          contestedFactCount: 1,
          contestedKeys: ["preferred_name"],
          missingEvidence: [],
          retrievalConfidence: 0.4,
        },
      },
    } as never,
    inferenceMetadata: {
      answerSource: "model",
      modelCallCount: 1,
      dataConfidence: "medium",
      evidenceSufficiency: "partial",
    },
    now: new Date("2026-07-05T00:00:00.000Z"),
  });

  assert.equal(ledger.version, "claim_confidence.v1");
  assert.equal(ledger.summary.contestedMemoryCount, 2);
  assert.equal(ledger.summary.lowConfidenceClaims >= 1, true);
  assert.notEqual(ledger.summary.uncertaintyAction, "answer");
});

test("buildClaimLedger treats successful web/tool evidence as verified", () => {
  const ledger = buildClaimLedger({
    route: "shared_brain",
    workload: "research",
    inferenceMetadata: {
      answerSource: "model",
      modelCallCount: 1,
      webGroundingUsed: true,
      webSourceCount: 3,
      dataConfidence: "high",
      evidenceSufficiency: "strong",
      toolResults: [{ tool: "web.search", ok: true, durationMs: 52 }],
    },
    now: new Date("2026-07-05T00:00:00.000Z"),
  });

  assert.equal(ledger.summary.uncertaintyAction, "answer");
  assert.equal(ledger.summary.verifiedEvidenceCount >= 2, true);
  assert.equal(ledger.summary.claimSourceCounts.tool_verified >= 2, true);
  assert.equal(ledger.summary.claimConfidence >= 0.7, true);
});

test("buildClaimLedger requests tool evidence for artifact work without proof", () => {
  const ledger = buildClaimLedger({
    route: "shared_brain",
    workload: "document_generate",
    requestMetadata: {
      understanding: {
        envelopeConfidence: 0.88,
        envelope: {
          desired_outputs: [{ kind: "pdf" }],
          required_capabilities: [{ name: "document.export" }],
          ambiguities: [],
        },
      },
    },
    inferenceMetadata: {
      answerSource: "model",
      modelCallCount: 1,
      dataConfidence: "low",
      evidenceSufficiency: "weak",
      blocks: [{ type: "document_block" }],
    },
    now: new Date("2026-07-05T00:00:00.000Z"),
  });

  assert.equal(ledger.summary.uncertaintyAction, "call_tool");
  assert.equal(ledger.summary.missingEvidenceCount >= 1, true);
  assert.equal(
    ledger.claims.some((claim) => claim.id === "missing_required_tool_evidence"),
    true,
  );
});

test("applyClaimConfidenceMetadata is flag gated and content safe", () => {
  const app = {
    config: {
      ELYAN_CLAIM_CONFIDENCE_V1_ENABLED: false,
      ELYAN_CLAIM_CONFIDENCE_SHADOW_ENABLED: false,
    },
  };
  const input = {
    userId: "11111111-1111-4111-8111-111111111111",
    metadata: {
      answerSource: "model",
      prompt: "private prompt",
      content: "private content",
      dataConfidence: "low",
      evidenceSufficiency: "weak",
    },
  };

  assert.equal(applyClaimConfidenceMetadata(app, input), input.metadata);

  const enabled = applyClaimConfidenceMetadata(
    {
      config: {
        ELYAN_CLAIM_CONFIDENCE_V1_ENABLED: false,
        ELYAN_CLAIM_CONFIDENCE_SHADOW_ENABLED: true,
      },
    },
    input,
  );

  assert.equal(enabled.claimConfidenceMode, "shadow");
  assert.equal(enabled.claimConfidenceVersion, "claim_confidence.v1");
  assert.equal(enabled.prompt, "private prompt");
  assert.equal(enabled.content, "private content");

  const safeMetadata = buildClaimConfidenceMetadata(buildClaimLedger({
    inferenceMetadata: input.metadata,
    now: new Date("2026-07-05T00:00:00.000Z"),
  }));
  assert.equal(safeMetadata.prompt, undefined);
  assert.equal(safeMetadata.content, undefined);
});

test("buildClaimConfidencePromptDirective emits bounded directives only when enabled", () => {
  const ledger = buildClaimLedger({
    inferenceMetadata: {
      answerSource: "model",
      dataConfidence: "low",
      evidenceSufficiency: "weak",
    },
    now: new Date("2026-07-05T00:00:00.000Z"),
  });

  assert.equal(
    buildClaimConfidencePromptDirective({ config: { ELYAN_CLAIM_CONFIDENCE_V1_ENABLED: false } }, ledger),
    null,
  );
  assert.match(
    buildClaimConfidencePromptDirective({ config: { ELYAN_CLAIM_CONFIDENCE_V1_ENABLED: true } }, ledger) ?? "",
    /evidence is incomplete|evidence/i,
  );
});
