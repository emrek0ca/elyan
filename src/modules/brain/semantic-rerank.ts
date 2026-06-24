import type { FastifyBaseLogger } from "fastify";

export type SemanticRerankCandidate = {
  title: string;
  content: string;
  score: number;
};

export type SemanticEmbedder = {
  embedBatch(texts: string[]): Promise<number[][]>;
};

export type SemanticRerankInput<T extends SemanticRerankCandidate> = {
  query: string;
  candidates: T[];
  enabled: boolean;
  modelName?: string;
  windowSize?: number;
  embedder?: SemanticEmbedder;
  logger?: Pick<FastifyBaseLogger, "warn" | "debug">;
};

export type SemanticRerankResult<T extends SemanticRerankCandidate> = {
  results: T[];
  used: boolean;
  degradedReason: string | null;
};

const DEFAULT_SEMANTIC_MODEL = "Xenova/multilingual-e5-small";
const MAX_TEXT_LENGTH = 1_200;

const embedderCache = new Map<string, Promise<SemanticEmbedder | null>>();

function compactText(value: string): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function normalizeRange(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return 0;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) {
    return 0.5;
  }
  return clamp((value - min) / (max - min), 0, 1);
}

function cosineSimilarity(left: number[], right: number[]): number {
  const length = Math.min(left.length, right.length);
  if (length <= 0) {
    return 0;
  }

  let dot = 0;
  let leftMagnitude = 0;
  let rightMagnitude = 0;

  for (let index = 0; index < length; index += 1) {
    const leftValue = Number(left[index] ?? 0);
    const rightValue = Number(right[index] ?? 0);
    dot += leftValue * rightValue;
    leftMagnitude += leftValue * leftValue;
    rightMagnitude += rightValue * rightValue;
  }

  if (leftMagnitude <= 0 || rightMagnitude <= 0) {
    return 0;
  }

  return dot / Math.sqrt(leftMagnitude * rightMagnitude);
}

function formatQueryText(value: string): string {
  return `query: ${compactText(value).slice(0, MAX_TEXT_LENGTH)}`;
}

function buildCandidateText(input: SemanticRerankCandidate): string {
  return compactText([input.title, input.content].filter(Boolean).join("\n\n")).slice(0, MAX_TEXT_LENGTH);
}

function tensorOutputToVectors(output: unknown): number[][] {
  const tensor = output as {
    data?: ArrayLike<number>;
    dims?: number[];
    shape?: number[];
    tolist?: () => unknown;
  } | null;

  const dims = Array.isArray(tensor?.dims) ? tensor.dims : Array.isArray(tensor?.shape) ? tensor.shape : [];
  const data = tensor?.data ? Array.from(tensor.data, (value) => Number(value)) : null;

  if (dims.length >= 1 && data && data.length > 0) {
    if (dims.length === 1) {
      return [data.slice(0, dims[0])];
    }

    if (dims.length === 2) {
      const [, columns] = dims;
      if (columns > 0) {
        const rows = Math.min(dims[0], Math.floor(data.length / columns));
        return Array.from({ length: rows }, (_, rowIndex) =>
          data.slice(rowIndex * columns, rowIndex * columns + columns),
        );
      }
    }
  }

  if (tensor && typeof tensor.tolist === "function") {
    const listed = tensor.tolist();
    if (Array.isArray(listed)) {
      if (listed.length > 0 && Array.isArray(listed[0])) {
        return (listed as number[][]).map((row) => row.map((value) => Number(value)));
      }
      if (listed.length > 0) {
        return [listed.map((value) => Number(value))];
      }
    }
  }

  if (Array.isArray(output)) {
    if (output.length > 0 && Array.isArray(output[0])) {
      return (output as unknown[]).map((row) => (Array.isArray(row) ? row.map((value) => Number(value)) : []));
    }
    return [output.map((value) => Number(value))];
  }

  return [];
}

async function loadSemanticEmbedder(
  modelName: string,
  logger?: Pick<FastifyBaseLogger, "warn" | "debug">,
): Promise<SemanticEmbedder | null> {
  const modelKey = compactText(modelName) || DEFAULT_SEMANTIC_MODEL;
  const cached = embedderCache.get(modelKey);
  if (cached) {
    return cached;
  }

  const pending = (async () => {
    try {
      const { pipeline } = await import("@huggingface/transformers");
      const extractor = await pipeline("feature-extraction", modelKey, { device: "cpu" });
      return {
        async embedBatch(texts: string[]) {
          const promptBatch = texts.map((text, index) => (index === 0 ? formatQueryText(text) : `passage: ${compactText(text).slice(0, MAX_TEXT_LENGTH)}`));
          const output = await extractor(promptBatch, { pooling: "mean", normalize: true });
          return tensorOutputToVectors(output);
        },
      } satisfies SemanticEmbedder;
    } catch (error) {
      logger?.warn(
        { error, modelName: modelKey },
        "Semantic rerank model unavailable; continuing with lexical and hashed retrieval only.",
      );
      return null;
    }
  })();

  embedderCache.set(modelKey, pending);
  return pending;
}

export async function rerankSemanticCandidates<T extends SemanticRerankCandidate>(
  input: SemanticRerankInput<T>,
): Promise<SemanticRerankResult<T>> {
  const query = compactText(input.query);
  if (!input.enabled || !query || input.candidates.length <= 1) {
    return {
      results: input.candidates,
      used: false,
      degradedReason: null,
    };
  }

  const windowSize = Math.max(2, Math.min(input.windowSize ?? 8, input.candidates.length));
  const windowCandidates = input.candidates.slice(0, windowSize);
  const embedder = input.embedder ?? (await loadSemanticEmbedder(input.modelName ?? DEFAULT_SEMANTIC_MODEL, input.logger));
  if (!embedder) {
    return {
      results: input.candidates,
      used: false,
      degradedReason: "semantic_rerank_unavailable",
    };
  }

  try {
    const vectors = await embedder.embedBatch([query, ...windowCandidates.map((candidate) => buildCandidateText(candidate))]);
    const queryVector = vectors[0] ?? [];
    const passageVectors = vectors.slice(1);
    if (queryVector.length === 0 || passageVectors.length !== windowCandidates.length) {
      return {
        results: input.candidates,
        used: false,
        degradedReason: "semantic_rerank_embeddings_unavailable",
      };
    }

    const minOriginal = Math.min(...windowCandidates.map((candidate) => candidate.score));
    const maxOriginal = Math.max(...windowCandidates.map((candidate) => candidate.score));
    const rerankedWindow = windowCandidates
      .map((candidate, index) => {
        const semanticScore = clamp(cosineSimilarity(queryVector, passageVectors[index] ?? []), 0, 1);
        const originalScore = normalizeRange(candidate.score, minOriginal, maxOriginal);
        const blendedScore = Number((originalScore * 0.58 + semanticScore * 0.42).toFixed(6));
        return {
          candidate,
          semanticScore,
          blendedScore,
        };
      })
      .sort((left, right) => {
        if (right.blendedScore !== left.blendedScore) {
          return right.blendedScore - left.blendedScore;
        }
        if (right.semanticScore !== left.semanticScore) {
          return right.semanticScore - left.semanticScore;
        }
        return right.candidate.score - left.candidate.score;
      })
      .map((entry) => entry.candidate);

    return {
      results: [...rerankedWindow, ...input.candidates.slice(windowSize)],
      used: true,
      degradedReason: null,
    };
  } catch (error) {
    input.logger?.warn?.({ error, modelName: input.modelName ?? DEFAULT_SEMANTIC_MODEL }, "Semantic rerank failed; using fallback ranking.");
    return {
      results: input.candidates,
      used: false,
      degradedReason: "semantic_rerank_failed",
    };
  }
}
