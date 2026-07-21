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

function freeOnlyApp() {
  return {
    config: {
      GEMINI_FREE_ONLY: true,
      GEMINI_API_KEY: "free-key",
      GEMINI_FAST_MODEL: "gemini-free-model",
      ELYAN_GEMINI_FREE_FEATURES_ENABLED: true,
      GEMINI_FREE_DATA_USAGE_ATTESTED: true,
      GEMINI_FREE_MODEL_ALLOWLIST: "gemini-free-model",
      GEMINI_FREE_DAILY_REQUEST_LIMIT: 1_000,
      GEMINI_FREE_USER_DAILY_REQUEST_LIMIT: 100,
      GEMINI_FREE_DAILY_INPUT_TOKEN_LIMIT: 1_000_000,
      GEMINI_PAID_FALLBACK_ENABLED: false,
      GEMINI_PAID_DATA_PROCESSING_ATTESTED: false,
    },
    services: {
      reliability: {
        store: {
          async get() {
            return null;
          },
          async increment() {
            return 1;
          },
          async incrementBy(_key: string, amount: number) {
            return amount;
          },
          async set() {},
        },
      },
    },
  } as never;
}

test("free-only Gemini eligibility does not depend on paid fallback flags", async () => {
  const permit = await acquireGeminiInferencePermit(freeOnlyApp(), {
    ...baseInput,
    model: "gemini-free-model",
    dataSharingConsentValidated: false,
  });

  assert.equal(permit.allowed, true);
  assert.equal(permit.mode, "free");
  assert.equal(permit.reason, "allowed");
});

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

test("paid Gemini fallback fails closed without billing attestation", async () => {
  assert.equal(
    (
      await acquireGeminiInferencePermit(
        paidApp({ GEMINI_PAID_DATA_PROCESSING_ATTESTED: false }),
        baseInput,
      )
    ).reason,
    "paid_data_processing_not_attested",
  );
});

test("paid Gemini fallback fails closed without data sharing consent", async () => {
  const permit = await acquireGeminiInferencePermit(paidApp(), {
    ...baseInput,
    dataSharingConsentValidated: false,
  });

  assert.equal(permit.allowed, false);
  assert.equal(permit.mode, "paid");
  assert.equal(permit.reason, "data_sharing_consent_required");
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
