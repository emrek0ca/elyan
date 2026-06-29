import type { FastifyBaseLogger } from "fastify";

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
 * it as the primary similarity signal. The model bytes are reused (cached in
 * @huggingface/transformers' module cache), so storage embeddings cost no
 * extra model RAM beyond the rerank that's already loaded.
 */

const STORAGE_SEMANTIC_MODEL = "Xenova/multilingual-e5-small";
export const STORAGE_SEMANTIC_DIMENSIONS = 384;
export const STORAGE_SEMANTIC_MODEL_TAG = "elyan_e5_small_384_v1";
const MAX_TEXT_LENGTH = 1_200;

type Extractor = (
  input: string | string[],
  options?: { pooling?: string; normalize?: boolean },
) => Promise<unknown>;

let extractorPromise: Promise<Extractor | null> | null = null;
let modelDisabled = false;

function compactText(value: string): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function tensorToVectors(output: unknown): number[][] {
  const tensor = output as {
    data?: ArrayLike<number>;
    dims?: number[];
    shape?: number[];
  } | null;
  const dims = Array.isArray(tensor?.dims)
    ? tensor!.dims!
    : Array.isArray(tensor?.shape)
      ? tensor!.shape!
      : [];
  const data = tensor?.data ? Array.from(tensor.data, (v) => Number(v)) : null;
  if (!data || data.length === 0 || dims.length < 1) {
    return [];
  }
  if (dims.length === 1) {
    return [data.slice(0, dims[0])];
  }
  if (dims.length >= 2) {
    const rows = dims[0];
    const cols = dims[dims.length - 1];
    const out: number[][] = [];
    for (let i = 0; i < rows; i += 1) {
      out.push(data.slice(i * cols, (i + 1) * cols));
    }
    return out;
  }
  return [];
}

async function getExtractor(
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
): Promise<Extractor | null> {
  if (modelDisabled) return null;
  if (extractorPromise) return extractorPromise;
  extractorPromise = (async () => {
    try {
      const { pipeline } = (await import("@huggingface/transformers")) as {
        pipeline: (task: string, model: string, opts: { device: string }) => Promise<Extractor>;
      };
      const extractor = await pipeline("feature-extraction", STORAGE_SEMANTIC_MODEL, {
        device: "cpu",
      });
      logger?.info?.(
        { model: STORAGE_SEMANTIC_MODEL, dims: STORAGE_SEMANTIC_DIMENSIONS },
        "storage semantic embedder loaded",
      );
      return extractor;
    } catch (error) {
      modelDisabled = true;
      logger?.warn?.(
        { error, model: STORAGE_SEMANTIC_MODEL },
        "storage semantic embedder unavailable; storage embeddings will use hash fallback",
      );
      return null;
    }
  })();
  return extractorPromise;
}

/**
 * Encodes a batch of texts (with e5's `passage:` prefix) into 384-dim
 * normalized vectors. Returns null when the model is unavailable so callers
 * can fall back to the hash embedding cheaply.
 */
export async function embedTextsForStorage(
  texts: string[],
  logger?: Pick<FastifyBaseLogger, "warn" | "info" | "debug">,
): Promise<number[][] | null> {
  if (texts.length === 0) return [];
  const extractor = await getExtractor(logger);
  if (!extractor) return null;
  try {
    const prepared = texts.map((text) => `passage: ${compactText(text).slice(0, MAX_TEXT_LENGTH)}`);
    const output = await extractor(prepared, { pooling: "mean", normalize: true });
    const vectors = tensorToVectors(output);
    if (vectors.length !== texts.length) return null;
    for (const v of vectors) {
      if (v.length !== STORAGE_SEMANTIC_DIMENSIONS) return null;
    }
    return vectors;
  } catch (error) {
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
): Promise<number[] | null> {
  const extractor = await getExtractor(logger);
  if (!extractor) return null;
  try {
    const output = await extractor([
      `query: ${compactText(query).slice(0, MAX_TEXT_LENGTH)}`,
    ], { pooling: "mean", normalize: true });
    const vectors = tensorToVectors(output);
    if (vectors.length !== 1 || vectors[0].length !== STORAGE_SEMANTIC_DIMENSIONS) {
      return null;
    }
    return vectors[0];
  } catch (error) {
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
