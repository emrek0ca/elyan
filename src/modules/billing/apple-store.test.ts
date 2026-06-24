import assert from "node:assert/strict";
import test from "node:test";
import type { AppEnv } from "../../config/env.js";
import { verifyAppleNotification, verifyAppleTransaction } from "./apple-store.js";

const config = {
  APPLE_APP_BUNDLE_ID: "com.elyan.elyanMobile",
  APPLE_APP_ID: 6779045459,
} as AppEnv;

test("Apple transaction verification fails closed for unsigned payloads", async () => {
  await assert.rejects(
    verifyAppleTransaction(config, "unsigned-transaction"),
    (error: Error) => error.message === "apple_signed_data_verification_failed",
  );
});

test("Apple notification verification fails closed for unsigned payloads", async () => {
  await assert.rejects(
    verifyAppleNotification(config, "unsigned-notification"),
    (error: Error) => error.message === "apple_signed_data_verification_failed",
  );
});
