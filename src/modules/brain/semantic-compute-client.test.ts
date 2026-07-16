import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  embedTextsWithSemanticWorker,
  getSemanticComputeMetrics,
  isSemanticComputeWorkerUnavailable,
  resetSemanticComputeWorkerForTests,
  setSemanticComputeDispatcherForTests,
} from "./semantic-compute-client.js";
import { rerankSemanticCandidates } from "./semantic-rerank.js";

test("production semantic model is baked as q8 and warmed only by the API process", async () => {
  const [dockerfile, workerSource, buildAppSource, indexSource] = await Promise.all([
    readFile("Dockerfile", "utf8"),
    readFile("src/modules/brain/semantic-compute-worker.ts", "utf8"),
    readFile("src/app/build-app.ts", "utf8"),
    readFile("src/index.ts", "utf8"),
  ]);

  assert.match(dockerfile, /dtype:\s*'q8'/);
  assert.match(dockerfile, /ELYAN_SEMANTIC_MODEL_LOCAL_ONLY=true/);
  assert.match(workerSource, /dtype:\s*"q8"/);
  assert.doesNotMatch(buildAppSource, /maybeStartSemanticV2Backfill/);
  assert.match(indexSource, /maybeStartSemanticV2Backfill\(app\)/);
});

test("semantic compute client fails closed when the worker is disabled", async () => {
  const previous = process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = "false";
  resetSemanticComputeWorkerForTests();

  const vectors = await embedTextsWithSemanticWorker({
    modelName: "Xenova/multilingual-e5-small",
    texts: ["query: test"],
  });

  assert.equal(vectors, null);
  assert.equal(isSemanticComputeWorkerUnavailable(), true);

  if (previous === undefined) {
    delete process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  } else {
    process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = previous;
  }
  resetSemanticComputeWorkerForTests();
});

test("semantic rerank falls back to original order when worker compute is unavailable", async () => {
  const previous = process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = "false";
  resetSemanticComputeWorkerForTests();

  const candidates = [
    { title: "First", content: "First candidate.", score: 0.9 },
    { title: "Second", content: "Second candidate.", score: 0.8 },
  ];
  const warnings: unknown[] = [];

  const result = await rerankSemanticCandidates({
    query: "Anything",
    candidates,
    enabled: true,
    logger: {
      warn(value: unknown) {
        warnings.push(value);
      },
      debug() {},
    },
  });

  assert.equal(result.used, false);
  assert.equal(result.degradedReason, "semantic_rerank_embeddings_unavailable");
  assert.deepEqual(result.results, candidates);
  assert.equal(warnings.length > 0, true);

  if (previous === undefined) {
    delete process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED;
  } else {
    process.env.ELYAN_SEMANTIC_COMPUTE_WORKER_ENABLED = previous;
  }
  resetSemanticComputeWorkerForTests();
});

test("semantic compute batches unique texts and coalesces concurrent duplicates", async () => {
  resetSemanticComputeWorkerForTests();
  const batches: string[][] = [];
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    batches.push(texts);
    return texts.map((text) => [text.length, 1]);
  });

  try {
    const [first, second] = await Promise.all([
      embedTextsWithSemanticWorker({
        modelName: "test-model",
        cacheScope: "tenant-a",
        texts: ["query: alpha", "passage: beta"],
      }),
      embedTextsWithSemanticWorker({
        modelName: "test-model",
        cacheScope: "tenant-a",
        texts: ["query: alpha", "passage: gamma"],
      }),
    ]);

    assert.deepEqual(first, [[12, 1], [13, 1]]);
    assert.deepEqual(second, [[12, 1], [14, 1]]);
    assert.equal(batches.length, 1);
    assert.deepEqual(batches[0], ["query: alpha", "passage: beta", "passage: gamma"]);

    const metrics = getSemanticComputeMetrics();
    assert.equal(metrics.requests, 2);
    assert.equal(metrics.workerRequests, 1);
    assert.equal(metrics.batches, 1);
    assert.equal(metrics.computedTexts, 3);
    assert.equal(metrics.coalescedTexts, 1);
    assert.equal(metrics.cacheEntries, 3);
    assert.equal(metrics.latencyMs.p95 >= 0, true);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic compute reuses hashed in-memory cache without another worker request", async () => {
  resetSemanticComputeWorkerForTests();
  let dispatchCount = 0;
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    dispatchCount += 1;
    return texts.map(() => [0.4, 0.6]);
  });

  try {
    const input = {
      modelName: "test-model",
      cacheScope: "tenant-a",
      texts: ["private preference"],
    };
    assert.deepEqual(await embedTextsWithSemanticWorker(input), [[0.4, 0.6]]);
    assert.deepEqual(await embedTextsWithSemanticWorker(input), [[0.4, 0.6]]);

    const metrics = getSemanticComputeMetrics();
    assert.equal(dispatchCount, 1);
    assert.equal(metrics.workerRequests, 1);
    assert.equal(metrics.cacheHits, 1);
    assert.equal(metrics.cacheEntries, 1);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic compute isolates cache entries by privacy scope and returned vectors by value", async () => {
  resetSemanticComputeWorkerForTests();
  let dispatchCount = 0;
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    dispatchCount += 1;
    return texts.map(() => [0.25, 0.75]);
  });

  try {
    const first = await embedTextsWithSemanticWorker({
      modelName: "test-model",
      cacheScope: "tenant-a",
      texts: ["same private text"],
    });
    first![0]![0] = 999;

    const sameTenant = await embedTextsWithSemanticWorker({
      modelName: "test-model",
      cacheScope: "tenant-a",
      texts: ["same private text"],
    });
    const otherTenant = await embedTextsWithSemanticWorker({
      modelName: "test-model",
      cacheScope: "tenant-b",
      texts: ["same private text"],
    });

    assert.deepEqual(sameTenant, [[0.25, 0.75]]);
    assert.deepEqual(otherTenant, [[0.25, 0.75]]);
    assert.equal(dispatchCount, 2);
    assert.equal(getSemanticComputeMetrics().cacheEntries, 2);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic compute keeps worker micro-batches bounded", async () => {
  resetSemanticComputeWorkerForTests();
  const batchSizes: number[] = [];
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    batchSizes.push(texts.length);
    return texts.map((_, index) => [index]);
  });

  try {
    const vectors = await embedTextsWithSemanticWorker({
      modelName: "test-model",
      texts: Array.from({ length: 40 }, (_, index) => `text-${index}`),
    });

    assert.equal(vectors?.length, 40);
    assert.equal(batchSizes.length, 2);
    assert.equal(Math.max(...batchSizes) <= 32, true);
    assert.equal(batchSizes.reduce((sum, size) => sum + size, 0), 40);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic compute caps concurrent worker batches under burst load", async () => {
  resetSemanticComputeWorkerForTests();
  let active = 0;
  let maxActive = 0;
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    active += 1;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1;
    return texts.map(() => [1]);
  });

  try {
    const vectors = await embedTextsWithSemanticWorker({
      modelName: "test-model",
      texts: Array.from({ length: 96 }, (_, index) => `burst-${index}`),
    });

    assert.equal(vectors?.length, 96);
    assert.equal(maxActive <= 2, true);
    assert.equal(getSemanticComputeMetrics().workerRequests, 3);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic compute includes queue wait in the caller timeout budget", async () => {
  resetSemanticComputeWorkerForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    await new Promise((resolve) => setTimeout(resolve, 25));
    return texts.map(() => [1]);
  });

  try {
    const vectors = await embedTextsWithSemanticWorker({
      modelName: "test-model",
      texts: Array.from({ length: 96 }, (_, index) => `deadline-${index}`),
      timeoutMs: 10,
    });

    assert.equal(vectors, null);
    assert.equal(getSemanticComputeMetrics().workerRequests, 2);
    assert.equal(getSemanticComputeMetrics().timeouts > 0, true);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("coalesced semantic callers keep independent timeout deadlines", async () => {
  resetSemanticComputeWorkerForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    await new Promise((resolve) => setTimeout(resolve, 20));
    return texts.map(() => [0.5]);
  });

  try {
    const [longBudget, shortBudget] = await Promise.all([
      embedTextsWithSemanticWorker({
        modelName: "test-model",
        cacheScope: "tenant-a",
        texts: ["same query"],
        timeoutMs: 50,
      }),
      embedTextsWithSemanticWorker({
        modelName: "test-model",
        cacheScope: "tenant-a",
        texts: ["same query"],
        timeoutMs: 5,
      }),
    ]);

    assert.deepEqual(longBudget, [[0.5]]);
    assert.equal(shortBudget, null);
    assert.equal(getSemanticComputeMetrics().workerRequests, 1);
    assert.equal(getSemanticComputeMetrics().coalescedTexts, 1);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic scheduler expires an earlier deadline without waiting for an older timer", async () => {
  resetSemanticComputeWorkerForTests();
  setSemanticComputeDispatcherForTests(async ({ texts }) => {
    await new Promise((resolve) => setTimeout(resolve, 30));
    return texts.map(() => [1]);
  });

  try {
    const occupying = embedTextsWithSemanticWorker({
      modelName: "test-model",
      texts: Array.from({ length: 64 }, (_, index) => `occupy-${index}`),
      timeoutMs: 100,
    });
    await new Promise((resolve) => setTimeout(resolve, 4));
    const olderQueued = embedTextsWithSemanticWorker({
      modelName: "test-model",
      texts: ["older-queued"],
      timeoutMs: 100,
    });
    const shortQueued = embedTextsWithSemanticWorker({
      modelName: "test-model",
      texts: ["short-queued"],
      timeoutMs: 10,
    });

    assert.equal(await shortQueued, null);
    await new Promise((resolve) => setTimeout(resolve, 4));
    assert.equal(getSemanticComputeMetrics().queuedTexts, 1);
    await Promise.all([occupying, olderQueued]);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});

test("semantic reset fences late dispatcher completions", async () => {
  resetSemanticComputeWorkerForTests();
  let release: (vectors: number[][]) => void = () => undefined;
  setSemanticComputeDispatcherForTests(({ texts }) => new Promise((resolve) => {
    release = () => resolve(texts.map(() => [1]));
  }));

  const pendingResult = embedTextsWithSemanticWorker({
    modelName: "test-model",
    cacheScope: "tenant-a",
    texts: ["late-result"],
  });
  await new Promise((resolve) => setTimeout(resolve, 4));
  resetSemanticComputeWorkerForTests();
  release([[1]]);

  assert.equal(await pendingResult, null);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(getSemanticComputeMetrics().activeBatches, 0);
  assert.equal(getSemanticComputeMetrics().cacheEntries, 0);
  assert.equal(getSemanticComputeMetrics().computedTexts, 0);
});

test("semantic compute fails closed when a batched dispatcher fails", async () => {
  resetSemanticComputeWorkerForTests();
  setSemanticComputeDispatcherForTests(async () => null);

  try {
    const vectors = await embedTextsWithSemanticWorker({
      modelName: "test-model",
      texts: ["query: unavailable"],
    });

    assert.equal(vectors, null);
    assert.equal(getSemanticComputeMetrics().failedBatches, 1);
  } finally {
    resetSemanticComputeWorkerForTests();
  }
});
