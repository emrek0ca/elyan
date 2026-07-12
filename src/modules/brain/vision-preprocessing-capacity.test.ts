import assert from "node:assert/strict";
import test from "node:test";
import type { FastifyInstance } from "fastify";
import {
  runVisionPreprocessingWithCapacity,
  VisionPreprocessingCapacityError,
} from "./vision-preprocessing-capacity.js";

const appWithoutRedis = {} as FastifyInstance;

test("vision preprocessing permits only one active operation per user", async () => {
  let finish: (() => void) | undefined;
  const first = runVisionPreprocessingWithCapacity({
    app: appWithoutRedis,
    userId: "vision-user-a",
    operation: () => new Promise<void>((resolve) => { finish = resolve; }),
  });
  await Promise.resolve();
  await assert.rejects(
    runVisionPreprocessingWithCapacity({
      app: appWithoutRedis,
      userId: "vision-user-a",
      operation: async () => undefined,
    }),
    (error: unknown) => error instanceof VisionPreprocessingCapacityError && error.code === "capacity",
  );
  finish?.();
  await first;
});

test("timed out native work retains its permit until the operation settles", async () => {
  let finish: (() => void) | undefined;
  await assert.rejects(
    runVisionPreprocessingWithCapacity({
      app: appWithoutRedis,
      userId: "vision-user-timeout",
      timeoutMs: 5,
      operation: () => new Promise<void>((resolve) => { finish = resolve; }),
    }),
    (error: unknown) => error instanceof VisionPreprocessingCapacityError && error.code === "timeout",
  );
  await assert.rejects(
    runVisionPreprocessingWithCapacity({
      app: appWithoutRedis,
      userId: "vision-user-timeout",
      operation: async () => undefined,
    }),
    (error: unknown) => error instanceof VisionPreprocessingCapacityError && error.code === "capacity",
  );
  finish?.();
  await new Promise((resolve) => setTimeout(resolve, 0));
});
