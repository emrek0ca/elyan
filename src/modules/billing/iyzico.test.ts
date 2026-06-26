import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { buildIyzicoCustomer, IyzicoClient } from "./iyzico.js";
import type { AppEnv } from "../../config/env.js";

function createEnv(): AppEnv {
  return {
    NODE_ENV: "test",
    HOST: "127.0.0.1",
    PORT: 4000,
    LOG_LEVEL: "silent",
    APP_BASE_URL: "https://api.example.com",
    DATABASE_URL: "postgres://postgres:postgres@127.0.0.1:5432/elyan_backend",
    JWT_SECRET: "change-me-please-1234",
    ACCESS_TOKEN_TTL: "15m",
    REFRESH_TOKEN_TTL: "30d",
    RUNTIME_TOKEN_TTL: "12h",
    PAIRING_TTL_MINUTES: 10,
    RUNTIME_SECRET_PEPPER: "change-me-runtime-pepper-1234",
    CORS_ORIGIN: "*",
    RELIABILITY_REDIS_REQUIRED: false,
    BLOB_STORAGE_BUCKET: "",
    BLOB_STORAGE_REGION: "",
    BLOB_STORAGE_ENDPOINT: "",
    BLOB_STORAGE_ACCESS_KEY_ID: "",
    BLOB_STORAGE_SECRET_ACCESS_KEY: "",
    BLOB_STORAGE_FORCE_PATH_STYLE: false,
    BLOB_STORAGE_SIGNED_URL_TTL_SECONDS: 600,
    BLOB_HMAC_SECRET: "",
    RATE_LIMIT_REDIS_ENABLED: false,
    REALTIME_REDIS_FANOUT_ENABLED: true,
    REALTIME_REDIS_CHANNEL_PREFIX: "elyan:realtime",
    REALTIME_EVENT_RETENTION_HOURS: 48,
    SSE_MAX_STREAMS_PER_USER: 4,
    SSE_REPLAY_LIMIT: 500,
    SSE_HEARTBEAT_MS: 15000,
    BRAIN_CIRCUIT_FAILURE_THRESHOLD: 3,
    BRAIN_CIRCUIT_OPEN_MS: 30000,
    TASK_DISPATCH_LOCK_TTL_MS: 120000,
    REQUEST_BUDGET_WINDOW_MS: 60000,
    AUTH_REQUEST_BUDGET_MAX: 20,
    CHAT_REQUEST_BUDGET_MAX: 60,
    TASK_REQUEST_BUDGET_MAX: 60,
    GOOGLE_CLIENT_ID: "",
    GOOGLE_SERVER_CLIENT_ID: "",
    GOOGLE_REVERSED_CLIENT_ID: "",
    APPLE_CLIENT_ID: "",
    APPLE_SERVICE_ID: "",
    APPLE_TEAM_ID: "",
    APPLE_IAP_SHARED_SECRET: "",
    APPLE_APP_STORE_ISSUER_ID: "",
    APPLE_APP_STORE_KEY_ID: "",
    APPLE_APP_STORE_PRIVATE_KEY: "",
    APPLE_APP_STORE_PRIVATE_KEY_PATH: "",
    APPLE_APP_BUNDLE_ID: "",
    APPLE_APP_ID: 0,
    APPLE_SOLO_PRODUCT_ID: "com.elyan.elyanMobile.solo.monthly",
    APPLE_PRO_PRODUCT_ID: "com.elyan.elyanMobile.pro.monthly",
    APNS_KEY_ID: "",
    APNS_PRIVATE_KEY: "",
    APNS_PRIVATE_KEY_PATH: "",
    APNS_ENVIRONMENT: "sandbox",
    ANDROID_APP_LINK_PACKAGE_NAME: "",
    ANDROID_SHA256_CERT_FINGERPRINTS: "",
    GOOGLE_PLAY_PACKAGE_NAME: "",
    GOOGLE_PLAY_SERVICE_ACCOUNT_EMAIL: "",
    GOOGLE_PLAY_PRIVATE_KEY: "",
    OPENAI_API_KEY: "",
    OPENAI_BASE_URL: "https://api.openai.com/v1",
    ANTHROPIC_API_KEY: "",
    ANTHROPIC_BASE_URL: "https://api.anthropic.com/v1",
    GROQ_API_KEY: "",
    GROQ_BASE_URL: "https://api.groq.com/openai/v1",
    GROQ_REASONING_MODEL: "openai/gpt-oss-120b",
    GROQ_FAST_MODEL: "openai/gpt-oss-20b",
    GROQ_FALLBACK_MODEL: "qwen/qwen3.6-27b",
    GROQ_VISION_MODEL: "meta-llama/llama-4-scout-17b-16e-instruct",
    OPENROUTER_API_KEY: "",
    OPENROUTER_BASE_URL: "https://openrouter.ai/api/v1",
    IYZICO_API_KEY: "sandbox-api-key",
    IYZICO_SECRET_KEY: "sandbox-secret",
    IYZICO_MERCHANT_ID: "3404590",
    IYZICO_BASE_URL: "https://api.iyzipay.com",
    IYZICO_PUBLIC_BASE_URL: "https://api.example.com",
    IYZICO_LOCALE: "tr",
    IYZICO_PRODUCT_NAME: "Elyan Subscriptions",
    ELYAN_SHARED_BRAIN_PROVIDER: "ollama",
    ELYAN_SHARED_BRAIN_BASE_URL: "http://127.0.0.1:11434",
    ELYAN_SHARED_BRAIN_MODEL: "llama3.2",
    ELYAN_SHARED_BRAIN_FAST_MODEL: "qwen2.5-coder:3b",
    ELYAN_SHARED_BRAIN_BALANCED_MODEL: "qwen2.5:7b-instruct-q5_K_M",
    ELYAN_SHARED_BRAIN_PLANNING_MODEL: "qwen2.5:7b-instruct-q5_K_M",
    ELYAN_SHARED_BRAIN_KEEP_ALIVE: "30m",
    ELYAN_WEB_GROUNDING_ENABLED: true,
    ELYAN_WEB_SEARCH_BASE_URL: "https://html.duckduckgo.com/html/",
    ELYAN_WEB_GROUNDING_MAX_RESULTS: 4,
    ELYAN_WEB_GROUNDING_TIMEOUT_MS: 6500,
    ELYAN_RAG_SEMANTIC_RERANK_ENABLED: true,
    ELYAN_RAG_SEMANTIC_RERANK_MODEL: "Xenova/multilingual-e5-small",
    ELYAN_RAG_SEMANTIC_RERANK_WINDOW: 8,
    ELYAN_SHARED_BRAIN_SYSTEM_PROMPT:
      "You are Elyan, a local-first assistant developed by Osman Emre Koca. Speak as Elyan, not as a generic chatbot. Act like a senior AI engineer: be concise, grounded, and explicit about architecture, failure modes, verification, tradeoffs, and operational safety. Prefer Turkish unless the user writes in another language. If asked who built you or what you are, say Elyan developed by Osman Emre Koca. Do not mention other AI brands or model names unless the user explicitly asks about implementation details. Never invent readiness, capabilities, or results. If uncertain, say so and suggest the smallest reliable verification step. Never reveal secrets, hostnames, API paths, private data, or hidden reasoning. If a request clearly requires a paired desktop runtime, say so briefly.",
    ELYAN_USER_UNDERSTANDING_ENABLED: true,
    ELYAN_PERSONALIZATION_ENABLED: true,
    ELYAN_WORLD_CONTEXT_PACKETS_ENABLED: true,
    ELYAN_LEARNING_EXTRACTION_ENABLED: true,
    ELYAN_BLOCKS_V11_ENABLED: false,
    ELYAN_UNDERSTANDING_DEBUG: false,
  };
}

test("buildIyzicoCustomer splits full name and mirrors address", () => {
  const customer = buildIyzicoCustomer({
    fullName: "Ada Lovelace",
    email: "ada@example.com",
    phone: "+905551112233",
    identityNumber: "12345678901",
    addressLine1: "Taksim 10",
    city: "Istanbul",
    country: "TR",
    zipCode: "34000",
  });

  assert.equal(customer.name, "Ada");
  assert.equal(customer.surname, "Lovelace");
  assert.equal(customer.billingAddress.address, "Taksim 10");
  assert.deepEqual(customer.billingAddress, customer.shippingAddress);
});

test("computeWebhookSignatureV3 matches subscription webhook formula", () => {
  const env = createEnv();
  const client = new IyzicoClient(env);
  const payload = {
    subscriptionReferenceCode: "sub-ref",
    customerReferenceCode: "customer-ref",
    orderReferenceCode: "order-ref",
    iyziEventType: "subscription.order.success",
  };

  const expected = createHmac(
    "sha256",
    env.IYZICO_SECRET_KEY ?? "",
  )
    .update(
      `${env.IYZICO_SECRET_KEY}${env.IYZICO_MERCHANT_ID}${payload.iyziEventType}${payload.subscriptionReferenceCode}${payload.orderReferenceCode}${payload.customerReferenceCode}`,
    )
    .digest("hex");

  assert.equal(client.computeWebhookSignatureV3(payload), expected);
});

test("computeWebhookSignatureV3 matches hosted payment page webhook formula", () => {
  const env = createEnv();
  const client = new IyzicoClient(env);
  const payload = {
    paymentConversationId: "conv-1",
    token: "checkout-token",
    iyziEventType: "CHECKOUT_FORM_AUTH",
    iyziPaymentId: "28157797",
    status: "SUCCESS",
  };

  const expected = createHmac("sha256", env.IYZICO_SECRET_KEY ?? "")
    .update(
      `${env.IYZICO_SECRET_KEY}${payload.iyziEventType}${payload.iyziPaymentId}${payload.token}${payload.paymentConversationId}${payload.status}`,
    )
    .digest("hex");

  assert.equal(client.computeWebhookSignatureV3(payload), expected);
});

test("normalizeSubscriptionStatus maps iyzico states to backend states", () => {
  const client = new IyzicoClient(createEnv());

  assert.equal(client.normalizeSubscriptionStatus("ACTIVE"), "active");
  assert.equal(client.normalizeSubscriptionStatus("trial"), "trialing");
  assert.equal(client.normalizeSubscriptionStatus("UNPAID"), "past_due");
  assert.equal(client.normalizeSubscriptionStatus("CANCELED"), "canceled");
});
