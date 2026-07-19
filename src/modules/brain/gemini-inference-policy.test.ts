import assert from "node:assert/strict";
import test from "node:test";
import { acquireGeminiInferencePermit } from "./gemini-inference-policy.js";

function paidApp(overrides: Record<string, unknown> = {}) {
  return {
    config: {
      GEMINI_FREE_ONLY: false,
      GEMINI_API_KEY: "paid-key",
      GEMINI_FAST_MODEL: "fast-model",
      GEMINI_PAID_FALLBACK_ENABLED: true,
      GEMINI_PAID_DATA_PROCESSING_ATTESTED: true,
      ...overrides,
    },
  } as never;
}

const baseInput = {
  feature: "brain_response" as const,
  userId: "user-1",
  model: "fast-model",
  requestPayload: { messages: [{ role: "user", content: "Merhaba" }] },
  dataSharingConsentValidated: true,
};

test("paid Gemini fallback allows consented conversation context", async () => {
  const permit = await acquireGeminiInferencePermit(paidApp(), {
    ...baseInput,
    dataLineage: {
      profile: true,
      memory: true,
      conversationHistory: true,
    },
  });

  assert.equal(permit.allowed, true);
  assert.equal(permit.mode, "paid");
});

test("paid Gemini fallback fails closed without billing attestations or consent", async () => {
  assert.equal(
    (
      await acquireGeminiInferencePermit(
        paidApp({ GEMINI_PAID_DATA_PROCESSING_ATTESTED: false }),
        baseInput,
      )
    ).reason,
    "paid_data_processing_not_attested",
  );
  assert.equal(
    (
      await acquireGeminiInferencePermit(paidApp(), {
        ...baseInput,
        dataSharingConsentValidated: false,
      })
    ).reason,
    "data_sharing_consent_required",
  );
});

test("paid Gemini fallback still blocks local, connector and unapproved attachment data", async () => {
  for (const input of [
    { ...baseInput, sensitivity: "restricted" as const },
    { ...baseInput, sensitivity: "sensitive" as const },
    { ...baseInput, dataLineage: { connector: true } },
    { ...baseInput, dataLineage: { mcp: true } },
    { ...baseInput, dataLineage: { accountData: true } },
    { ...baseInput, dataLineage: { toolResult: true } },
    {
      ...baseInput,
      dataLineage: { attachment: true },
      userAuthorizedCloud: false,
    },
  ]) {
    const permit = await acquireGeminiInferencePermit(paidApp(), input);
    assert.equal(permit.allowed, false);
    assert.equal(permit.reason, "private_data_blocked");
  }
});

test("paid Gemini fallback accepts an attachment only after explicit cloud authorization", async () => {
  const permit = await acquireGeminiInferencePermit(paidApp(), {
    ...baseInput,
    dataLineage: { attachment: true },
    userAuthorizedCloud: true,
  });

  assert.equal(permit.allowed, true);
});
