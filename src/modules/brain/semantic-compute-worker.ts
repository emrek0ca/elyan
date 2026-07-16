import { parentPort } from "node:worker_threads";
import { env, pipeline } from "@huggingface/transformers";

type SemanticComputeRequest = {
  id: number;
  task: "embed";
  modelName: string;
  texts: string[];
};

type Extractor = (
  input: string | string[],
  options?: { pooling?: string; normalize?: boolean },
) => Promise<unknown>;

const extractors = new Map<string, Promise<Extractor>>();

const semanticModelCacheDir = process.env.ELYAN_SEMANTIC_MODEL_CACHE_DIR?.trim();
if (semanticModelCacheDir) {
  env.cacheDir = semanticModelCacheDir;
}

const semanticModelsLocalOnly =
  process.env.ELYAN_SEMANTIC_MODEL_LOCAL_ONLY === "true";
const semanticModelRevision =
  process.env.ELYAN_SEMANTIC_MODEL_REVISION?.trim() || "main";

function tensorOutputToVectors(output: unknown): number[][] {
  const tensor = output as {
    data?: ArrayLike<number>;
    dims?: number[];
    shape?: number[];
    tolist?: () => unknown;
  } | null;

  const dims = Array.isArray(tensor?.dims)
    ? tensor.dims
    : Array.isArray(tensor?.shape)
      ? tensor.shape
      : [];
  const data = tensor?.data ? Array.from(tensor.data, (value) => Number(value)) : null;

  if (dims.length >= 1 && data && data.length > 0) {
    if (dims.length === 1) {
      return [data.slice(0, dims[0])];
    }
    const columns = dims[dims.length - 1];
    if (columns > 0) {
      const rows = Math.min(dims[0], Math.floor(data.length / columns));
      return Array.from({ length: rows }, (_, rowIndex) =>
        data.slice(rowIndex * columns, rowIndex * columns + columns),
      );
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

  return [];
}

function getExtractor(modelName: string): Promise<Extractor> {
  const cached = extractors.get(modelName);
  if (cached) return cached;
  const pending = pipeline("feature-extraction", modelName, {
    device: "cpu",
    // The q8 artifact preserves the multilingual e5 model while reducing the
    // production image/cold-start footprint from ~470 MB to ~118 MB.
    dtype: "q8",
    local_files_only: semanticModelsLocalOnly,
    revision: semanticModelRevision,
  }) as Promise<Extractor>;
  extractors.set(modelName, pending);
  return pending;
}

parentPort?.on("message", async (request: SemanticComputeRequest) => {
  try {
    if (request.task !== "embed") {
      throw new Error("unsupported_semantic_compute_task");
    }
    const extractor = await getExtractor(request.modelName);
    const output = await extractor(request.texts, {
      pooling: "mean",
      normalize: true,
    });
    parentPort?.postMessage({
      id: request.id,
      ok: true,
      vectors: tensorOutputToVectors(output),
    });
  } catch (error) {
    parentPort?.postMessage({
      id: request.id,
      ok: false,
      error: error instanceof Error ? error.message : "semantic_compute_failed",
    });
  }
});
