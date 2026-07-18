import test from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { buildIyzicoCustomer, IyzicoClient } from "./iyzico.js";
import { loadEnv, type AppEnv } from "../../config/env.js";

function createEnv(): AppEnv {
  // Elle kurulmuş 150+ alanlı sabit yerine gerçek zod fabrikası: yeni zorunlu
  // env alanları eklendiğinde bu test bir daha kırılmaz; iyzico'nun okuduğu
  // alanlar açıkça override edilir.
  return loadEnv({
    NODE_ENV: "test",
    LOG_LEVEL: "silent",
    APP_BASE_URL: "https://api.example.com",
    DATABASE_URL: "postgres://postgres:postgres@127.0.0.1:5432/elyan_backend",
    JWT_SECRET: "change-me-please-1234-at-least-32",
    RUNTIME_SECRET_PEPPER: "change-me-runtime-pepper-1234",
    IYZICO_API_KEY: "sandbox-api-key",
    IYZICO_SECRET_KEY: "sandbox-secret",
    IYZICO_MERCHANT_ID: "3404590",
    IYZICO_BASE_URL: "https://api.iyzipay.com",
    IYZICO_PUBLIC_BASE_URL: "https://api.example.com",
    IYZICO_LOCALE: "tr",
    IYZICO_PRODUCT_NAME: "Elyan Subscriptions",
  });
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
