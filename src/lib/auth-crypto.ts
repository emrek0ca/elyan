import { randomBytes, scrypt as scryptCallback, timingSafeEqual, createHmac } from "node:crypto";
import { promisify } from "node:util";

const scrypt = promisify(scryptCallback);

export async function hashSecret(secret: string): Promise<string> {
  const salt = randomBytes(16).toString("hex");
  const derived = (await scrypt(secret, salt, 64)) as Buffer;
  return `${salt}:${derived.toString("hex")}`;
}

export async function verifySecret(secret: string, storedValue: string): Promise<boolean> {
  const [salt, hash] = storedValue.split(":");

  if (!salt || !hash) {
    return false;
  }

  const derived = (await scrypt(secret, salt, 64)) as Buffer;
  const hashedBuffer = Buffer.from(hash, "hex");

  if (hashedBuffer.length !== derived.length) {
    return false;
  }

  return timingSafeEqual(hashedBuffer, derived);
}

export function createOpaqueCode(bytes = 18): string {
  return randomBytes(bytes).toString("base64url");
}

export function createPairingCode(length = 8): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  return Array.from({ length }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join("");
}

export function deriveRuntimeDeviceSecret(input: {
  pairingSecret: string;
  pairSessionId: string;
  pairingCode: string;
  deviceId: string;
}): string {
  return createHmac("sha256", input.pairingSecret)
    .update(`${input.pairSessionId}:${input.pairingCode}:${input.deviceId}`)
    .digest("base64url");
}
