import { randomBytes, scryptSync, timingSafeEqual } from 'crypto';

const PASSWORD_KEY_LENGTH = 64;
const PASSWORD_SALT_LENGTH = 16;

export function normalizeIdentityEmail(email: string) {
  return email.trim().toLowerCase();
}

export function hashControlPlanePassword(password: string, salt = randomBytes(PASSWORD_SALT_LENGTH).toString('hex')) {
  const derivedKey = scryptSync(password, salt, PASSWORD_KEY_LENGTH) as Buffer;
  return {
    salt,
    hash: derivedKey.toString('hex'),
  };
}

export function verifyControlPlanePassword(
  password: string,
  salt: string,
  expectedHash: string
) {
  const actualHash = hashControlPlanePassword(password, salt).hash;
  const actual = Buffer.from(actualHash, 'hex');
  const expected = Buffer.from(expectedHash, 'hex');

  if (actual.length !== expected.length) {
    return false;
  }

  return timingSafeEqual(actual, expected);
}
