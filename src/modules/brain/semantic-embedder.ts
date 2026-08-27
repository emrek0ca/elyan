import type { FastifyBaseLogger } from "fastify";
import {
  embedTextsWithSemanticWorker,
  isSemanticComputeWorkerUnavailable,
} from "./semantic-compute-client.js";
import { collapseWhitespace as compactText } from "../../lib/text.js";

/**
 * Real (transformer-based) semantic embeddings for the storage layer.
 *
 * The original retrieval path uses a 256-dim SHA-token "hash embedding" — cheap
 * but semantically thin: paraphrases miss, multilingual coupling is weak. The
 * rerank already runs real `multilingual-e5-small`, but rerank can only reorder
 * the candidate window — it can't recover candidates the hash filter misses.
 *
 * This module exposes a 384-dim normalized embedding from the same e5-small
 * model so we can write a TRUE semantic vector alongside the hash one and use
 * it as the primary similarity signal. The heavy model runs behind the semantic
 * compute worker so API request handling keeps the hash fallback when compute
 * is slow or unavailable.
 */

const STORAGE_SEMANTIC_MODEL = "Xenova/multilingual-e5-small";
export const STORAGE_SEMANTIC_DIMENSIONS = 384;
export const STORAGE_SEMANTIC_MODEL_TAG = "elyan_e5_small_384_v1";
const MAX_TEXT_LENGTH = 1_200;

let modelDisabled = false;

/* In-process devre kesici: art arda batch hataları (ör. ONNX runtime'ın
 * geçici belleği tükenmesi) her isteği yeniden model çağrısıyla bekletmesin.
 * Eşik aşılırsa kısa bir cooldown boyunca embed çağrıları anında null döner
 * ve çağıranlar lexical/hash fallback'e düşer. */
const EMBEDDER_FAILURE_THRESHOLD = 5;
const EMBEDDER_COOLDOWN_MS = 60_000;
let consecutiveEmbedderFailures = 0;
let embedderCooldownUntil = 0;

function isEmbedderInCooldown(): boolean {
  return Date.now() < embedderCooldownUntil;
}

function recordEmbedderSuccess(): void {
  consecutiveEmbedderFailures = 0;
}

function recordEmbedderFailure(): void {
  consecutiveEmbedderFailures += 1;
  if (consecutiveEmbedderFailures >= EMBEDDER_FAILURE_THRESHOLD) {
    embedderCooldownUntil = Date.now() + EMBEDDER_COOLDOWN_MS;
    consecutiveEmbedderFailures = 0;
  }
}

/**
 * Encodes a batch of texts (with e5's `passage:` prefix) into 384-dim
 * normalized vectors. Returns null when the model is unavailable so callers
 * can fall back to the hash embedding cheaply.
 */
export async function embedTextsForStorage(
  texts: string[],
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
  cacheScope?: string,
  timeoutMs?: number,
): Promise<number[][] | null> {
  if (texts.length === 0) return [];
  if (isEmbedderInCooldown()) return null;
  try {
    const prepared = texts.map((text) => `passage: ${compactText(text).slice(0, MAX_TEXT_LENGTH)}`);
    const vectors = await embedTextsWithSemanticWorker({
      modelName: STORAGE_SEMANTIC_MODEL,
      texts: prepared,
      cacheScope,
      timeoutMs,
      logger,
    });
    if (!vectors) {
      modelDisabled = isSemanticComputeWorkerUnavailable();
      return null;
    }
    if (vectors.length !== texts.length) return null;
    for (const v of vectors) {
      if (v.length !== STORAGE_SEMANTIC_DIMENSIONS) return null;
    }
    recordEmbedderSuccess();
    return vectors;
  } catch (error) {
    recordEmbedderFailure();
    logger?.warn?.({ error }, "storage semantic embedding batch failed");
    return null;
  }
}

/**
 * Same shape but prefixed with `query:` for retrieval — e5 was trained with
 * different prefixes for queries vs passages, the difference is meaningful.
 */
export async function embedQueryForStorage(
  query: string,
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
  cacheScope?: string,
  timeoutMs?: number,
): Promise<number[] | null> {
  if (isEmbedderInCooldown()) return null;
  try {
    const vectors = await embedTextsWithSemanticWorker({
      modelName: STORAGE_SEMANTIC_MODEL,
      texts: [`query: ${compactText(query).slice(0, MAX_TEXT_LENGTH)}`],
      cacheScope,
      timeoutMs,
      logger,
    });
    if (!vectors) {
      modelDisabled = isSemanticComputeWorkerUnavailable();
      return null;
    }
    if (vectors.length !== 1 || vectors[0].length !== STORAGE_SEMANTIC_DIMENSIONS) {
      return null;
    }
    recordEmbedderSuccess();
    return vectors[0];
  } catch (error) {
    recordEmbedderFailure();
    logger?.warn?.({ error }, "storage semantic query embedding failed");
    return null;
  }
}

/**
 * Whether the storage embedder is currently usable. Cheap check (just reads
 * the cached disabled flag); does NOT trigger model load.
 */
export function isStorageEmbedderDisabled(): boolean {
  return modelDisabled;
}
