import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import type { AppEnv } from "../config/env.js";

function decodeKey(raw: string): Buffer {
  try {
    const normalized = raw.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, "=");
    const decoded = Buffer.from(padded, "base64");

    if (decoded.length !== 32) {
      throw new Error("TOKEN_ENCRYPTION_KEY must decode to exactly 32 bytes");
    }

    return decoded;
  } catch (error) {
    throw new Error(
      error instanceof Error ? error.message : "TOKEN_ENCRYPTION_KEY could not be decoded as base64",
    );
  }
}

function getEncryptionKey(env: AppEnv): Buffer {
  return decodeKey(env.TOKEN_ENCRYPTION_KEY ?? "");
}

export function encryptJson(env: AppEnv, payload: Record<string, unknown>): string {
  const key = getEncryptionKey(env);
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const plaintext = Buffer.from(JSON.stringify(payload), "utf8");
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const authTag = cipher.getAuthTag();

  return [iv.toString("base64url"), authTag.toString("base64url"), ciphertext.toString("base64url")].join(".");
}

export function decryptJson<T extends Record<string, unknown>>(env: AppEnv, sealedValue: string): T {
  const [ivRaw, authTagRaw, ciphertextRaw] = sealedValue.split(".");

  if (!ivRaw || !authTagRaw || !ciphertextRaw) {
    throw new Error("Encrypted payload has invalid format");
  }

  const key = getEncryptionKey(env);
  const decipher = createDecipheriv("aes-256-gcm", key, Buffer.from(ivRaw, "base64url"));
  decipher.setAuthTag(Buffer.from(authTagRaw, "base64url"));

  const plaintext = Buffer.concat([
    decipher.update(Buffer.from(ciphertextRaw, "base64url")),
    decipher.final(),
  ]);

  return JSON.parse(plaintext.toString("utf8")) as T;
}
