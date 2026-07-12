import type { FastifyInstance } from "fastify";
import { tryAcquireLoadSheddingPermit, type LoadSheddingPermit } from "../../lib/reliability/load-shedding.js";

const VISION_PREPROCESSING_GLOBAL_MAX = 2;
const VISION_PREPROCESSING_PER_USER_MAX = 1;
const VISION_PREPROCESSING_PERMIT_TTL_MS = 60_000;
export const VISION_PREPROCESSING_TIMEOUT_MS = 8_000;

let activeInProcess = 0;
const activeByUser = new Map<string, number>();

export class VisionPreprocessingCapacityError extends Error {
  readonly code: "capacity" | "timeout";

  constructor(code: "capacity" | "timeout") {
    super(code === "capacity" ? "vision preprocessing capacity unavailable" : "vision preprocessing timed out");
    this.name = "VisionPreprocessingCapacityError";
    this.code = code;
  }
}

type CapacityPermit = { release: () => Promise<void> };

async function tryAcquirePermit(app: FastifyInstance, userId: string): Promise<CapacityPermit | null> {
  if (
    activeInProcess >= VISION_PREPROCESSING_GLOBAL_MAX ||
    (activeByUser.get(userId) ?? 0) >= VISION_PREPROCESSING_PER_USER_MAX
  ) return null;
  activeInProcess += 1;
  activeByUser.set(userId, (activeByUser.get(userId) ?? 0) + 1);
  const releaseInProcess = () => {
    activeInProcess = Math.max(0, activeInProcess - 1);
    const remaining = Math.max(0, (activeByUser.get(userId) ?? 1) - 1);
    if (remaining === 0) activeByUser.delete(userId);
    else activeByUser.set(userId, remaining);
  };
  let userPermit: LoadSheddingPermit | null = null;
  let globalPermit: LoadSheddingPermit | null = null;
  try {
    userPermit = await tryAcquireLoadSheddingPermit(app, {
      namespace: `vision_preprocessing_user:${userId}`,
      maxConcurrent: VISION_PREPROCESSING_PER_USER_MAX,
      ttlMs: VISION_PREPROCESSING_PERMIT_TTL_MS,
      salt: userId,
    });
    if (!userPermit) return null;
    globalPermit = await tryAcquireLoadSheddingPermit(app, {
      namespace: "vision_preprocessing_global",
      maxConcurrent: VISION_PREPROCESSING_GLOBAL_MAX,
      ttlMs: VISION_PREPROCESSING_PERMIT_TTL_MS,
      salt: userId,
    });
    if (!globalPermit) return null;
    let released = false;
    return {
      release: async () => {
        if (released) return;
        released = true;
        releaseInProcess();
        await Promise.allSettled([globalPermit?.release(), userPermit?.release()]);
      },
    };
  } finally {
    if (!userPermit || !globalPermit) {
      releaseInProcess();
      await globalPermit?.release().catch(() => undefined);
      await userPermit?.release().catch(() => undefined);
    }
  }
}

export async function runVisionPreprocessingWithCapacity<T>(input: {
  app: FastifyInstance;
  userId: string;
  operation: () => Promise<T>;
  timeoutMs?: number;
}): Promise<T> {
  const permit = await tryAcquirePermit(input.app, input.userId);
  if (!permit) throw new VisionPreprocessingCapacityError("capacity");

  const operation = Promise.resolve().then(input.operation);
  const timeoutMs = Math.max(250, input.timeoutMs ?? VISION_PREPROCESSING_TIMEOUT_MS);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new VisionPreprocessingCapacityError("timeout")), timeoutMs);
  });
  try {
    const result = await Promise.race([operation, timeout]);
    await permit.release().catch(() => undefined);
    return result;
  } catch (error) {
    if (error instanceof VisionPreprocessingCapacityError && error.code === "timeout") {
      // Keep capacity reserved until native image work actually settles.
      void operation.catch(() => undefined).finally(() => permit.release());
      throw error;
    }
    await permit.release().catch(() => undefined);
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
}
