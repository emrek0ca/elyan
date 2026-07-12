import type { FastifyInstance } from "fastify";
import { tryAcquireLoadSheddingPermit, type LoadSheddingPermit } from "../../lib/reliability/load-shedding.js";

const VISION_ESCALATION_GLOBAL_MAX = 2;
const VISION_ESCALATION_PER_USER_MAX = 1;
const VISION_ESCALATION_PERMIT_TTL_MS = 35_000;
let activeInProcess = 0;
const activeByUser = new Map<string, number>();

export type VisionEscalationPermit = { release: () => Promise<void> };

export async function tryAcquireVisionEscalationPermit(
  app: FastifyInstance,
  userId: string,
): Promise<VisionEscalationPermit | null> {
  if (
    activeInProcess >= VISION_ESCALATION_GLOBAL_MAX ||
    (activeByUser.get(userId) ?? 0) >= VISION_ESCALATION_PER_USER_MAX
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
      namespace: `vision_escalation_user:${userId}`,
      maxConcurrent: VISION_ESCALATION_PER_USER_MAX,
      ttlMs: VISION_ESCALATION_PERMIT_TTL_MS,
      salt: userId,
    });
    if (!userPermit) return null;
    globalPermit = await tryAcquireLoadSheddingPermit(app, {
      namespace: "vision_escalation_global",
      maxConcurrent: VISION_ESCALATION_GLOBAL_MAX,
      ttlMs: VISION_ESCALATION_PERMIT_TTL_MS,
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

export function canAffordVisionEscalation(input: {
  remainingCredits: number | null;
  estimatedPrimaryCredits: number;
  costGuardEnabled: boolean;
}): boolean {
  if (input.remainingCredits == null) return true;
  const reserve = input.costGuardEnabled
    ? Math.max(64, Math.ceil(input.estimatedPrimaryCredits * 0.75))
    : 32;
  return input.remainingCredits - input.estimatedPrimaryCredits >= reserve;
}
