import { createHash } from "node:crypto";
import type { FastifyInstance } from "fastify";
import type {
  DesktopWorkOrder,
  DesktopWorkOrderStep,
} from "./desktop-work-order.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import { DESKTOP_SKILL_MANIFEST } from "./desktop-skill-manifest.js";

const PLAN_CACHE_CONTRACT = "elyan.plan_cache.v1";
const PLAN_CACHE_MAX_ENTRIES = 512;
const PLAN_CACHE_TTL_MS = 15 * 60 * 1000;
const PLAN_CACHE_VALUE_VERSION = 2;
const PLAN_CACHE_LOCK_TTL_MS = 25_000;
const PLAN_CACHE_WAIT_TIMEOUT_MS = 1_800;
const PLAN_CACHE_WAIT_INTERVAL_MS = 120;
const PLAN_CACHE_COUNTER_MAX = Number.MAX_SAFE_INTEGER;

export type DesktopPlanCacheMetadata = {
  contract: typeof PLAN_CACHE_CONTRACT;
  status: "hit" | "stored";
  keyHash: string;
  source: "memory_lru" | "reliability_store";
  cachedAt: string;
  fingerprints: DesktopPlanCacheFingerprints;
  hitCount?: number;
};

export type DesktopPlanCacheFingerprints = {
  goalDeltaHash: string;
  capabilityManifestHash: string;
  skillManifestHash?: string;
};

type CacheEntry = {
  key: string;
  keyHash: string;
  steps: DesktopWorkOrderStep[];
  materializedCapabilityScope: string[];
  storedAtMs: number;
  cachedAt: string;
  fingerprints: DesktopPlanCacheFingerprints;
  hits: number;
};

const cache = new Map<string, CacheEntry>();

export type DesktopPlanCacheTelemetry = {
  reads: number;
  hits: number;
  memoryHits: number;
  reliabilityStoreHits: number;
  stores: number;
  reliabilityStoreWriteAttempts: number;
  reliabilityStoreWriteFailures: number;
  locksAcquired: number;
  locksContended: number;
  lockReleaseFailures: number;
  waitHits: number;
  waitMisses: number;
  deferredBehindPlanner: number;
  estimatedPromptBytesAvoided: number;
  estimatedPlanTokensAvoided: number;
};

const telemetry: DesktopPlanCacheTelemetry = {
  reads: 0,
  hits: 0,
  memoryHits: 0,
  reliabilityStoreHits: 0,
  stores: 0,
  reliabilityStoreWriteAttempts: 0,
  reliabilityStoreWriteFailures: 0,
  locksAcquired: 0,
  locksContended: 0,
  lockReleaseFailures: 0,
  waitHits: 0,
  waitMisses: 0,
  deferredBehindPlanner: 0,
  estimatedPromptBytesAvoided: 0,
  estimatedPlanTokensAvoided: 0,
};

function incrementTelemetry(
  key: keyof DesktopPlanCacheTelemetry,
  amount = 1,
): void {
  const next = telemetry[key] + amount;
  telemetry[key] = Number.isFinite(next)
    ? Math.min(PLAN_CACHE_COUNTER_MAX, Math.max(0, next))
    : PLAN_CACHE_COUNTER_MAX;
}

export function recordDesktopPlanCacheAvoidedCost(input: {
  promptBytes: number;
  estimatedTokens: number;
}): void {
  if (Number.isFinite(input.promptBytes) && input.promptBytes > 0) {
    incrementTelemetry("estimatedPromptBytesAvoided", input.promptBytes);
  }
  if (Number.isFinite(input.estimatedTokens) && input.estimatedTokens > 0) {
    incrementTelemetry("estimatedPlanTokensAvoided", input.estimatedTokens);
  }
}

export function recordDesktopPlanCacheDeferred(): void {
  incrementTelemetry("deferredBehindPlanner");
}

export function getDesktopPlanCacheTelemetry(): DesktopPlanCacheTelemetry {
  return { ...telemetry };
}

type PlanCacheStore = {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlMs?: number): Promise<void>;
  increment?(key: string, ttlMs: number): Promise<number>;
  acquireLock?(
    key: string,
    owner: string,
    ttlMs: number,
    requireRedis?: boolean,
  ): Promise<boolean>;
  releaseLock?(key: string, owner: string): Promise<boolean>;
};

const localLocks = new Set<string>();

function stableJson(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, nested]) => `${JSON.stringify(key)}:${stableJson(nested)}`)
    .join(",")}}`;
}

function digest(value: unknown): string {
  return createHash("sha256").update(stableJson(value)).digest("hex");
}

function normalizeText(value: unknown): string {
  return String(value ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .toLocaleLowerCase("tr-TR");
}

function sortedStrings(values: Iterable<unknown>): string[] {
  return [...values]
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
    .sort();
}

function allowedCapabilityManifest(allowedCapabilities: string[]) {
  const allowed = new Set(sortedStrings(allowedCapabilities));
  return DESKTOP_CAPABILITY_MANIFEST.filter((entry) => allowed.has(entry.name))
    .map((entry) => ({
      name: entry.name,
      requiredArgs: sortedStrings(entry.requiredArgs),
      requiresApproval: entry.requiresApproval,
      inputContract: entry.inputContract,
      outputContract: entry.outputContract,
      artifactContract: entry.artifactContract,
      verificationPlan: entry.verificationPlan,
      privacyClass: entry.privacyClass,
      skillAffinity: sortedStrings(entry.skillAffinity),
    }))
    .sort((left, right) => left.name.localeCompare(right.name));
}

function relevantSkillManifest(allowedCapabilities: string[]) {
  if (!allowedCapabilities.includes("run_skill")) return null;
  return DESKTOP_SKILL_MANIFEST.map((entry) => ({
    id: entry.id,
    requiredParameters: sortedStrings(entry.requiredParameters),
    parameters: sortedStrings(entry.parameters),
    stepCapabilities: sortedStrings(entry.stepCapabilities),
    requiresConfirmation: entry.requiresConfirmation,
    inputContract: entry.inputContract,
    outputContract: entry.outputContract,
    verificationPlan: entry.verificationPlan,
  })).sort((left, right) => left.id.localeCompare(right.id));
}

export function buildDesktopPlanCacheFingerprints(
  workOrder: DesktopWorkOrder,
  allowedCapabilities: string[],
): DesktopPlanCacheFingerprints {
  const pack = workOrder.contextPack;
  const conversationState = pack?.conversationState ?? {};
  const skillManifest = relevantSkillManifest(allowedCapabilities);
  return {
    goalDeltaHash: digest({
      sourceTextHash: workOrder.goal.sourceTextHash,
      goalSummaryHash: digest(normalizeText(workOrder.goal.summary)),
      currentGoalHash: digest(normalizeText(conversationState.currentGoal)),
      latestArtifactRef: pack?.latestArtifactRef ?? null,
      outputContract: pack?.outputContract ?? null,
      expectedOutputs: workOrder.expectedOutputs,
    }).slice(0, 32),
    capabilityManifestHash: digest(
      allowedCapabilityManifest(allowedCapabilities),
    ).slice(0, 32),
    ...(skillManifest
      ? { skillManifestHash: digest(skillManifest).slice(0, 32) }
      : {}),
  };
}

function cacheSubject(workOrder: DesktopWorkOrder, allowedCapabilities: string[]) {
  const pack = workOrder.contextPack;
  const outputContract = pack?.outputContract ?? {};
  const privacyRouting = pack?.privacyRouting ?? {};
  const toolSkillDecision = pack?.toolSkillDecision ?? {};
  const latestArtifactRef = pack?.latestArtifactRef ?? null;
  const conversationState = pack?.conversationState ?? {};
  const remoteMcp = workOrder.remoteMcp ?? null;
  const fingerprints = buildDesktopPlanCacheFingerprints(
    workOrder,
    allowedCapabilities,
  );
  return {
    contract: PLAN_CACHE_CONTRACT,
    schema: workOrder.schema,
    source: workOrder.source,
    fingerprints,
    goalHash: digest({
      kind: workOrder.goal.kind,
      summary: normalizeText(workOrder.goal.summary),
      language: workOrder.goal.language,
      sourceTextHash: workOrder.goal.sourceTextHash,
    }),
    entitiesHash: digest(
      workOrder.entities.map((entity) => ({
        type: entity.type,
        value: normalizeText(entity.value),
      })),
    ),
    constraintsHash: digest(workOrder.constraints.map(normalizeText)),
    expectedOutputsHash: digest(workOrder.expectedOutputs),
    verificationRulesHash: digest(workOrder.verificationRules),
    requiredCapabilities: sortedStrings(workOrder.requiredCapabilities),
    allowedCapabilities: sortedStrings(allowedCapabilities),
    materializablePolicyHash: digest({
      capabilityAuthorization: workOrder.capabilityAuthorization ?? null,
      workType: workOrder.workType ?? null,
      privacyClass: workOrder.planPreview.privacyClass,
      outputContract,
      privacyRouting,
      toolSkillDecision,
      latestArtifactRef,
      conversationState: {
        turnKind: conversationState.turnKind,
        carryForward: conversationState.carryForward,
        currentGoalHash: digest(normalizeText(conversationState.currentGoal)),
      },
      remoteMcp,
    }),
  };
}

function cloneSteps(steps: DesktopWorkOrderStep[]): DesktopWorkOrderStep[] {
  return steps.map((step) => {
    const cloned: DesktopWorkOrderStep = {
      ...step,
      args: { ...step.args },
    };
    if (step.dependsOn) cloned.dependsOn = [...step.dependsOn];
    if (step.resourceScope) cloned.resourceScope = [...step.resourceScope];
    if (step.forEach) cloned.forEach = step.forEach;
    return cloned;
  });
}

function storeFor(app?: FastifyInstance): PlanCacheStore | null {
  const store = app?.services?.reliability?.store as
    | Partial<PlanCacheStore>
    | undefined;
  return store &&
    typeof store.get === "function" &&
    typeof store.set === "function"
    ? (store as PlanCacheStore)
    : null;
}

function distributedKey(keyHash: string): string {
  return `tasks:desktop_plan_cache:v1:${keyHash}`;
}

function distributedHitKey(keyHash: string): string {
  return `tasks:desktop_plan_cache:v1:${keyHash}:hits`;
}

function distributedLockKey(keyHash: string): string {
  return `tasks:desktop_plan_cache:v1:${keyHash}:lock`;
}

function parseDistributedEntry(
  raw: string | null,
): {
  steps: DesktopWorkOrderStep[];
  materializedCapabilityScope: string[];
  cachedAt: string;
  fingerprints: DesktopPlanCacheFingerprints;
} | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (
      parsed.version !== PLAN_CACHE_VALUE_VERSION ||
      parsed.contract !== PLAN_CACHE_CONTRACT
    ) {
      return null;
    }
    if (!Array.isArray(parsed.steps)) return null;
    if (!Array.isArray(parsed.materializedCapabilityScope)) return null;
    const steps = parsed.steps
      .filter(
        (step): step is DesktopWorkOrderStep =>
          step &&
          typeof step === "object" &&
          !Array.isArray(step) &&
          typeof (step as DesktopWorkOrderStep).id === "string" &&
          typeof (step as DesktopWorkOrderStep).capability === "string" &&
          typeof (step as DesktopWorkOrderStep).description === "string" &&
          (step as DesktopWorkOrderStep).args &&
          typeof (step as DesktopWorkOrderStep).args === "object" &&
          !Array.isArray((step as DesktopWorkOrderStep).args),
      )
      .map((step) => ({
        ...step,
        args: { ...step.args },
      }));
    if (steps.length === 0) return null;
    const materializedCapabilityScope = parsed.materializedCapabilityScope
      .map((value) => String(value ?? "").trim())
      .filter(Boolean);
    if (materializedCapabilityScope.length === 0) return null;
    const rawFingerprints =
      parsed.fingerprints &&
      typeof parsed.fingerprints === "object" &&
      !Array.isArray(parsed.fingerprints)
        ? (parsed.fingerprints as Record<string, unknown>)
        : null;
    const goalDeltaHash =
      typeof rawFingerprints?.goalDeltaHash === "string"
        ? rawFingerprints.goalDeltaHash.trim()
        : "";
    const capabilityManifestHash =
      typeof rawFingerprints?.capabilityManifestHash === "string"
        ? rawFingerprints.capabilityManifestHash.trim()
        : "";
    if (!goalDeltaHash || !capabilityManifestHash) return null;
    const skillManifestHash =
      typeof rawFingerprints?.skillManifestHash === "string"
        ? rawFingerprints.skillManifestHash.trim()
        : "";
    return {
      steps,
      materializedCapabilityScope,
      fingerprints: {
        goalDeltaHash,
        capabilityManifestHash,
        ...(skillManifestHash ? { skillManifestHash } : {}),
      },
      cachedAt:
        typeof parsed.cachedAt === "string" && parsed.cachedAt.trim()
          ? parsed.cachedAt
          : new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

function pruneExpired(now = Date.now()): void {
  for (const [key, entry] of cache) {
    if (now - entry.storedAtMs >= PLAN_CACHE_TTL_MS) cache.delete(key);
  }
  while (cache.size > PLAN_CACHE_MAX_ENTRIES) {
    const oldest = cache.keys().next().value;
    if (!oldest) break;
    cache.delete(oldest);
  }
}

export function buildDesktopPlanCacheKey(
  workOrder: DesktopWorkOrder,
  allowedCapabilities: string[],
): { key: string; keyHash: string } {
  const key = stableJson(cacheSubject(workOrder, allowedCapabilities));
  return { key, keyHash: digest(key).slice(0, 32) };
}

export async function readDesktopPlanCache(
  workOrder: DesktopWorkOrder,
  allowedCapabilities: string[],
  app?: FastifyInstance,
): Promise<{
  steps: DesktopWorkOrderStep[];
  materializedCapabilityScope: string[];
  metadata: DesktopPlanCacheMetadata;
} | null> {
  incrementTelemetry("reads");
  pruneExpired();
  const { key, keyHash } = buildDesktopPlanCacheKey(
    workOrder,
    allowedCapabilities,
  );
  const fingerprints = buildDesktopPlanCacheFingerprints(
    workOrder,
    allowedCapabilities,
  );
  const store = storeFor(app);
  if (store) {
    const distributed = parseDistributedEntry(
      await store.get(distributedKey(keyHash)).catch(() => null),
    );
    if (distributed) {
      incrementTelemetry("hits");
      incrementTelemetry("reliabilityStoreHits");
      const hitCount =
        typeof store.increment === "function"
          ? await store
              .increment(distributedHitKey(keyHash), PLAN_CACHE_TTL_MS)
              .catch(() => 1)
          : 1;
      return {
        steps: cloneSteps(distributed.steps),
        materializedCapabilityScope: [
          ...distributed.materializedCapabilityScope,
        ],
        metadata: {
          contract: PLAN_CACHE_CONTRACT,
          status: "hit",
          keyHash,
          source: "reliability_store",
          cachedAt: distributed.cachedAt,
          fingerprints: distributed.fingerprints,
          hitCount,
        },
      };
    }
  }
  const entry = cache.get(key);
  if (!entry) return null;
  incrementTelemetry("hits");
  incrementTelemetry("memoryHits");
  cache.delete(key);
  entry.hits += 1;
  entry.storedAtMs = Date.now();
  cache.set(key, entry);
  return {
    steps: cloneSteps(entry.steps),
    materializedCapabilityScope: [...entry.materializedCapabilityScope],
    metadata: {
      contract: PLAN_CACHE_CONTRACT,
      status: "hit",
      keyHash,
      source: "memory_lru",
      cachedAt: entry.cachedAt,
      fingerprints: entry.fingerprints,
      hitCount: entry.hits,
    },
  };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function acquireDesktopPlanMaterializationLock(
  workOrder: DesktopWorkOrder,
  allowedCapabilities: string[],
  app?: FastifyInstance,
): Promise<{
  acquired: boolean;
  keyHash: string;
  owner: string;
  source: "reliability_store" | "memory_lru";
}> {
  const { key, keyHash } = buildDesktopPlanCacheKey(
    workOrder,
    allowedCapabilities,
  );
  const store = storeFor(app);
  const owner = createHash("sha256")
    .update(`${keyHash}:${Date.now()}:${Math.random()}`)
    .digest("hex")
    .slice(0, 32);
  if (store?.acquireLock) {
    const acquired = await store
      .acquireLock(distributedLockKey(keyHash), owner, PLAN_CACHE_LOCK_TTL_MS)
      .catch(() => false);
    incrementTelemetry(acquired ? "locksAcquired" : "locksContended");
    return {
      acquired,
      keyHash,
      owner,
      source: "reliability_store",
    };
  }
  if (localLocks.has(key)) {
    incrementTelemetry("locksContended");
    return { acquired: false, keyHash, owner: key, source: "memory_lru" };
  }
  localLocks.add(key);
  incrementTelemetry("locksAcquired");
  return { acquired: true, keyHash, owner: key, source: "memory_lru" };
}

export async function releaseDesktopPlanMaterializationLock(input: {
  workOrder: DesktopWorkOrder;
  allowedCapabilities: string[];
  owner: string;
  app?: FastifyInstance;
}): Promise<void> {
  const { key, keyHash } = buildDesktopPlanCacheKey(
    input.workOrder,
    input.allowedCapabilities,
  );
  const store = storeFor(input.app);
  if (store?.releaseLock) {
    const released = await store
      .releaseLock(distributedLockKey(keyHash), input.owner)
      .catch(() => false);
    if (!released) incrementTelemetry("lockReleaseFailures");
    return;
  }
  localLocks.delete(input.owner || key);
}

export async function waitForDesktopPlanCache(input: {
  workOrder: DesktopWorkOrder;
  allowedCapabilities: string[];
  app?: FastifyInstance;
  timeoutMs?: number;
}): Promise<Awaited<ReturnType<typeof readDesktopPlanCache>>> {
  const deadline = Date.now() + (input.timeoutMs ?? PLAN_CACHE_WAIT_TIMEOUT_MS);
  while (Date.now() < deadline) {
    await sleep(PLAN_CACHE_WAIT_INTERVAL_MS);
    const cached = await readDesktopPlanCache(
      input.workOrder,
      input.allowedCapabilities,
      input.app,
    );
    if (cached) {
      incrementTelemetry("waitHits");
      return cached;
    }
  }
  incrementTelemetry("waitMisses");
  return null;
}

export async function storeDesktopPlanCache(input: {
  workOrder: DesktopWorkOrder;
  allowedCapabilities: string[];
  steps: DesktopWorkOrderStep[];
  materializedCapabilityScope: string[];
  app?: FastifyInstance;
}): Promise<DesktopPlanCacheMetadata> {
  incrementTelemetry("stores");
  pruneExpired();
  const { key, keyHash } = buildDesktopPlanCacheKey(
    input.workOrder,
    input.allowedCapabilities,
  );
  const fingerprints = buildDesktopPlanCacheFingerprints(
    input.workOrder,
    input.allowedCapabilities,
  );
  const cachedAt = new Date().toISOString();
  cache.set(key, {
    key,
    keyHash,
    steps: cloneSteps(input.steps),
    materializedCapabilityScope: [...input.materializedCapabilityScope],
    storedAtMs: Date.now(),
    cachedAt,
    fingerprints,
    hits: 0,
  });
  const store = storeFor(input.app);
  if (store) {
    incrementTelemetry("reliabilityStoreWriteAttempts");
    await store
      .set(
        distributedKey(keyHash),
        JSON.stringify({
          version: PLAN_CACHE_VALUE_VERSION,
          contract: PLAN_CACHE_CONTRACT,
          cachedAt,
          fingerprints,
          steps: cloneSteps(input.steps),
          materializedCapabilityScope: [
            ...input.materializedCapabilityScope,
          ],
        }),
        PLAN_CACHE_TTL_MS,
      )
      .catch(() => {
        incrementTelemetry("reliabilityStoreWriteFailures");
      });
  }
  pruneExpired();
  return {
    contract: PLAN_CACHE_CONTRACT,
    status: "stored",
    keyHash,
    source: store ? "reliability_store" : "memory_lru",
    cachedAt,
    fingerprints,
  };
}

export function clearDesktopPlanCacheForTests(): void {
  cache.clear();
  localLocks.clear();
  for (const key of Object.keys(telemetry) as Array<
    keyof DesktopPlanCacheTelemetry
  >) {
    telemetry[key] = 0;
  }
}
