import { createHash } from 'crypto';

export const RETRIEVAL_EMBEDDING_DIMENSIONS = 384;

function normalizeToken(token: string) {
  return token.toLowerCase().replace(/[^a-z0-9ğüşöçıİĞÜŞÖÇ-]+/giu, '').trim();
}

function hashToBucket(token: string, dimensions: number) {
  const digest = createHash('sha256').update(token).digest();
  return digest.readUInt32BE(0) % dimensions;
}

function hashToSign(token: string) {
  const digest = createHash('sha256').update(`${token}:sign`).digest();
  return digest[0] % 2 === 0 ? 1 : -1;
}

export function normalizeRetrievalText(value: string) {
  return value.replace(/\s+/g, ' ').replace(/\u0000/g, ' ').trim();
}

export function truncateRetrievalText(value: string, maxLength = 4_000) {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength - 1).trimEnd()}…`;
}

export function buildTextEmbedding(text: string, dimensions = RETRIEVAL_EMBEDDING_DIMENSIONS) {
  const vector = new Array<number>(dimensions).fill(0);
  const normalized = normalizeRetrievalText(text.toLowerCase());
  const tokens = normalized
    .split(/[^a-z0-9ğüşöçıİĞÜŞÖÇ-]+/giu)
    .map(normalizeToken)
    .filter((token) => token.length > 1);

  if (tokens.length === 0) {
    return vector;
  }

  for (const [index, token] of tokens.entries()) {
    const tokenBucket = hashToBucket(token, dimensions);
    const sign = hashToSign(token);
    vector[tokenBucket] += sign;

    if (index > 0) {
      const bigram = `${tokens[index - 1]}_${token}`;
      vector[hashToBucket(bigram, dimensions)] += hashToSign(bigram) * 0.5;
    }
  }

  const norm = Math.sqrt(vector.reduce((total, entry) => total + entry * entry, 0));
  if (norm === 0) {
    return vector;
  }

  return vector.map((entry) => Number((entry / norm).toFixed(6)));
}

export function toPgVectorLiteral(vector: number[]) {
  return `[${vector.map((value) => Number(value.toFixed(6))).join(',')}]`;
}
