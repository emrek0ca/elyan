import { createHash } from "node:crypto";
import { and, eq, or, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { learningEvents, taskEpisodes } from "../../db/schema.js";
import type { OutcomeAssessment } from "./outcome-verdict.js";
import { recordTaskEpisode } from "./episode-store.js";

/**
 * Model-merkezli agent öğrenmesinin görev başına, redakte edilmiş kayıt
 * sözleşmesi. Ham kullanıcı metni, ham araç çıktısı ve yapılandırılmış özel
 * argümanlar bu kayda hiçbir zaman girmez.
 */
export const AGENT_TRAJECTORY_CONTRACT = "elyan.agent_trajectory.v1" as const;
export const AGENT_TRAJECTORY_EVENT_TYPE = "agent_trajectory" as const;
export const AGENT_TRAJECTORY_EVENT_KEY = "trajectory" as const;

const MAX_CAPABILITIES = 128;
const MAX_PLAN_STEPS = 16;
const MAX_TOOL_EVENTS = 32;
const MAX_ERROR_CODES = 12;
const MAX_SAFE_ARG_KEYS = 24;
const MAX_HASH_TEXT_LENGTH = 4_096;

const PRIVATE_KEY_PATTERN =
  /(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key|message[_-]?body|prompt|content|raw|access[_-]?token|refresh[_-]?token)/iu;
const PRIVATE_VALUE_PATTERNS = [
  /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/iu,
  /\b(?:\+?\d[\s().-]?){10,}\b/u,
  /\b(?:api[_-]?key|secret|token|bearer|password|jwt|credential)\b/iu,
  /\b(?:sk|pk|ghp|glpat|xoxb|xoxp)-[A-Za-z0-9_=-]{12,}\b/u,
  /\b(?:\d[ -]*?){13,19}\b/u,
];
const PRIVATE_PATH_PATTERN =
  /(?:^|[\\/])(?:Users|home|Documents|Desktop|Downloads|Library|AppData|\.ssh)(?:[\\/]|$)/iu;

export type AgentTrajectoryVerdict = OutcomeAssessment["verdict"];

export type AgentTrajectoryRecord = {
  contract: typeof AGENT_TRAJECTORY_CONTRACT;
  version: 1;
  episodeId: string;
  taskId: string;
  request: {
    contentIncluded: false;
    summary: "redacted";
    sha256: string;
    lengthBucket: string;
    language: "tr" | "en" | "unknown";
  };
  platform: {
    targetKind: "desktop" | "mobile" | "server" | "unknown";
    platform: string | null;
    targetDeviceIdSha256: string | null;
    onlineAtAdmission: boolean | null;
    liveCapabilities: string[];
  };
  modelDecision: {
    route: string | null;
    intent: string | null;
    targetDevice: string | null;
    confidence: number | null;
    requiredCapabilities: string[];
    missingInformation: { present: boolean; sha256: string | null };
    requiresConfirmation: boolean;
    goalContract: {
      objectiveSha256: string | null;
      constraintsCount: number;
      successCriteriaCount: number;
      ambiguityPolicy: string | null;
    };
    provider: string | null;
    model: string | null;
    artifactVersion: string | null;
    decisionSource: string | null;
  };
  plan: {
    source: string | null;
    revision: number | null;
    steps: Array<{
      sequence: number;
      id: string;
      device: string | null;
      capability: string;
      dependsOn: string[];
      args: Record<string, unknown>;
      redactedArgKeys: string[];
    }>;
  };
  toolCalls: Array<{
    sequence: number;
    tool: string;
    args: Record<string, unknown>;
    redactedArgKeys: string[];
    ok: boolean;
    verified: boolean | null;
    attempt: number | null;
    latencyMs: number | null;
    errorCode: string | null;
    result: {
      contentIncluded: false;
      outputKind: string | null;
      resultSha256: string | null;
      stateReadbackObserved: boolean | null;
      stateReadbackKeys: string[];
    };
  }>;
  approval: {
    required: boolean;
    capabilities: string[];
    decision: "approved" | "rejected" | "not_required" | "unknown";
  };
  verification: {
    status: "passed" | "partial" | "failed" | "unknown";
    evidenceKinds: string[];
    evidenceCount: number;
    explicit: boolean;
  };
  replanning: {
    occurred: boolean;
    count: number;
    reasons: string[];
  };
  outcome: {
    verdict: AgentTrajectoryVerdict;
    reasons: string[];
  };
  telemetry: {
    latencyMs: number | null;
    retryCount: number;
    errorCodes: string[];
  };
  privacy: {
    rawPromptIncluded: false;
    rawToolResultsIncluded: false;
    rawToolArgsIncluded: false;
    redaction: "hash_only_default";
    trainingEligible: boolean;
    preferenceScope: "user";
  };
};

export type AgentTrajectoryInput = {
  task: {
    id: string;
    userId: string;
    targetDeviceId?: string | null;
    title?: string | null;
    payload?: unknown;
    result?: unknown;
    approvalRequest?: unknown;
    error?: string | null;
    createdAt?: Date | string | null;
    completedAt?: Date | string | null;
  };
  assessment: OutcomeAssessment;
  result?: unknown;
  latencyMs?: number;
};

function recordOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function stringValue(value: unknown, maxLength = 160): string | null {
  if (typeof value !== "string") return null;
  const compact = value.replace(/\s+/gu, " ").trim();
  if (!compact) return null;
  return compact.length <= maxLength
    ? compact
    : `${compact.slice(0, maxLength - 1).trimEnd()}…`;
}

function safeStringList(value: unknown, max = MAX_CAPABILITIES): string[] {
  if (!Array.isArray(value)) return [];
  const result: string[] = [];
  for (const item of value) {
    const normalized = safeLabel(item, 120);
    if (normalized && !result.includes(normalized)) result.push(normalized);
    if (result.length >= max) break;
  }
  return result;
}

/** Metadata'da yalnız sözleşme etiketi veya kısa digest tutulur. */
function safeLabel(value: unknown, maxLength = 120): string | null {
  const normalized = stringValue(value, maxLength)?.toLowerCase() ?? null;
  if (!normalized) return null;
  return /^[a-z0-9][a-z0-9._:/-]{1,119}$/u.test(normalized)
    ? normalized
    : `redacted_${sha256(normalized).slice(0, 16)}`;
}

function safeEnum(value: unknown, allowed: readonly string[]): string | null {
  const normalized = stringValue(value, 80)?.toLowerCase() ?? null;
  return normalized && allowed.includes(normalized) ? normalized : null;
}

function sha256(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

function boundedHash(value: unknown): string {
  if (typeof value === "string") {
    return sha256({ length: value.length, prefix: value.slice(0, MAX_HASH_TEXT_LENGTH) });
  }
  if (Array.isArray(value)) {
    return sha256({
      type: "array",
      length: value.length,
      sample: value.slice(0, 16).map((item) => boundedHash(item)),
    });
  }
  if (recordOf(value)) {
    const record = recordOf(value) as Record<string, unknown>;
    const keys = Object.keys(record);
    return sha256({
      type: "object",
      keys: keys.slice(0, MAX_SAFE_ARG_KEYS).map((key) => safeLabel(key, 80)),
      keyCount: keys.length,
    });
  }
  return sha256(value);
}

export function agentTrajectoryEpisodeId(taskId: string): string {
  return sha256(`${AGENT_TRAJECTORY_CONTRACT}:${String(taskId).trim()}`);
}

function lengthBucket(value: string): string {
  if (value.length === 0) return "empty";
  if (value.length <= 32) return "0_32";
  if (value.length <= 128) return "33_128";
  if (value.length <= 512) return "129_512";
  if (value.length <= 2_000) return "513_2000";
  return "2000_plus";
}

function languageFor(value: string): "tr" | "en" | "unknown" {
  if (!value) return "unknown";
  if (/[çğıöşüÇĞİÖŞÜ]/u.test(value)) return "tr";
  const turkishWords = /\b(?:ve|bir|için|icin|kapat|aç|ac|oluştur|olustur|kaydet)\b/iu;
  const englishWords = /\b(?:the|and|for|close|open|create|save|find)\b/iu;
  if (turkishWords.test(value)) return "tr";
  if (englishWords.test(value)) return "en";
  return "unknown";
}

function safePlatform(value: unknown): string | null {
  const normalized = stringValue(value, 40)?.toLowerCase() ?? null;
  if (!normalized) return null;
  return /^[a-z0-9._-]+$/u.test(normalized) ? normalized : null;
}

function targetKindFromPlatform(platform: string | null, route: string | null): AgentTrajectoryRecord["platform"]["targetKind"] {
  if (platform === "ios" || platform === "android") return "mobile";
  if (platform === "macos" || platform === "darwin" || platform === "windows" || platform === "linux") {
    return "desktop";
  }
  if (platform === "server" || route === "server_brain") return "server";
  if (route === "desktop_runtime" || route === "pairing_required") return "desktop";
  return "unknown";
}

function readPayloadRoot(task: AgentTrajectoryInput["task"]): Record<string, unknown> {
  return recordOf(task.payload) ?? {};
}

function readPayloadMetadata(payload: Record<string, unknown>): Record<string, unknown> {
  return recordOf(payload.metadata) ?? {};
}

function readResultRecord(input: AgentTrajectoryInput): Record<string, unknown> {
  return recordOf(input.result ?? input.task.result) ?? {};
}

function readNumber(root: Record<string, unknown> | null, ...keys: string[]): number | null {
  if (!root) return null;
  for (const key of keys) {
    const value = root[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function readBoolean(root: Record<string, unknown> | null, ...keys: string[]): boolean | null {
  if (!root) return null;
  for (const key of keys) {
    if (typeof root[key] === "boolean") return root[key] as boolean;
  }
  return null;
}

function readString(root: Record<string, unknown> | null, ...keys: string[]): string | null {
  if (!root) return null;
  for (const key of keys) {
    const value = stringValue(root[key]);
    if (value) return value;
  }
  return null;
}

function readArray(root: Record<string, unknown> | null, ...keys: string[]): unknown[] {
  if (!root) return [];
  for (const key of keys) {
    if (Array.isArray(root[key])) return root[key] as unknown[];
  }
  return [];
}

function privateValue(value: string): boolean {
  return PRIVATE_VALUE_PATTERNS.some((pattern) => pattern.test(value)) || PRIVATE_PATH_PATTERN.test(value);
}

function safeScalar(value: unknown, key: string, allowText: boolean): unknown {
  if (typeof value === "boolean" || typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value !== "string") {
    if (value === null) return null;
    return { kind: Array.isArray(value) ? "array" : "object" };
  }
  const normalized = value.replace(/\s+/gu, " ").trim();
  if (!normalized || PRIVATE_KEY_PATTERN.test(key) || privateValue(normalized)) {
    return { kind: "redacted", sha256: boundedHash(value), length: value.length };
  }
  if (PRIVATE_PATH_PATTERN.test(normalized) || /^(?:~|[A-Za-z]:[\\/]|\/)/u.test(normalized)) {
    return { kind: "path", sha256: boundedHash(normalized), length: normalized.length };
  }
  if (!allowText) {
    return { kind: "string", sha256: boundedHash(normalized), length: normalized.length };
  }
  return normalized.length <= 120
    ? normalized
    : { kind: "string", sha256: boundedHash(normalized), length: normalized.length };
}

function sanitizeArgs(value: unknown, privacyClass: string | null): { args: Record<string, unknown>; redactedArgKeys: string[] } {
  const input = recordOf(value) ?? {};
  const args: Record<string, unknown> = {};
  const redactedArgKeys: string[] = [];
  const allowText = privacyClass === "public_text";
  let keyCount = 0;
  for (const key of Object.keys(input)) {
    if (keyCount >= MAX_SAFE_ARG_KEYS) break;
    keyCount += 1;
    const rawValue = input[key];
    const normalizedKey = stringValue(key, 80);
    if (!normalizedKey) continue;
    const sanitized = safeScalar(rawValue, normalizedKey, allowText);
    args[normalizedKey] = sanitized;
    if (recordOf(sanitized)?.kind === "redacted" || recordOf(sanitized)?.kind === "path") {
      redactedArgKeys.push(normalizedKey);
    }
  }
  for (const key of Object.keys(input).slice(MAX_SAFE_ARG_KEYS)) redactedArgKeys.push(stringValue(key, 80) ?? "unknown");
  return { args, redactedArgKeys: [...new Set(redactedArgKeys)].slice(0, MAX_SAFE_ARG_KEYS) };
}

function readRouteDecision(payload: Record<string, unknown>, metadata: Record<string, unknown>): Record<string, unknown> {
  return (
    recordOf(metadata.routeDecision) ??
    recordOf(metadata.routingDecision) ??
    recordOf(payload.routeDecision) ??
    {}
  );
}

function readWorkOrder(payload: Record<string, unknown>): Record<string, unknown> {
  return recordOf(payload.desktopWorkOrder) ?? {};
}

function readExecutionContract(payload: Record<string, unknown>): Record<string, unknown> {
  return recordOf(payload.taskExecutionContract) ?? recordOf(readPayloadMetadata(payload).taskExecutionContract) ?? {};
}

function readGoalContract(
  workOrder: Record<string, unknown>,
  executionContract: Record<string, unknown>,
): AgentTrajectoryRecord["modelDecision"]["goalContract"] {
  const goal = recordOf(executionContract.goal) ?? {};
  const semanticGoal = recordOf(workOrder.semanticGoal) ?? {};
  const objective = stringValue(goal.objective) ?? stringValue(semanticGoal.objective);
  const constraints = readArray(goal, "constraints");
  const successCriteria = readArray(goal, "successCriteria");
  return {
    objectiveSha256: objective ? boundedHash(objective) : null,
    constraintsCount: constraints.length || readArray(semanticGoal, "constraints").length,
    successCriteriaCount: successCriteria.length || readArray(semanticGoal, "successCriteria").length,
    ambiguityPolicy: safeEnum(
      goal.ambiguityPolicy ?? semanticGoal.ambiguityPolicy,
      ["ask", "safe_assumption", "fail_closed"],
    ),
  };
}

function normalizedStep(
  raw: unknown,
  sequence: number,
  privacyClass: string | null,
): AgentTrajectoryRecord["plan"]["steps"][number] | null {
  const step = recordOf(raw);
  if (!step) return null;
  const capability = safeLabel(step.capability);
  const id = safeLabel(step.id) ?? `step_${sequence + 1}`;
  if (!capability) return null;
  const args = sanitizeArgs(step.args ?? step.input, privacyClass);
  return {
    sequence,
    id,
    device: safeLabel(step.device),
    capability,
    dependsOn: safeStringList(step.dependsOn, MAX_PLAN_STEPS),
    args: args.args,
    redactedArgKeys: args.redactedArgKeys,
  };
}

function readPlanSteps(
  payload: Record<string, unknown>,
  privacyClass: string | null,
): AgentTrajectoryRecord["plan"]["steps"] {
  const workOrder = readWorkOrder(payload);
  const preview = recordOf(workOrder.planPreview) ?? recordOf(payload.planPreview) ?? {};
  const execution = recordOf(payload.taskExecutionContract)?.execution;
  const executionRecord = recordOf(execution);
  const rawSteps =
    (Array.isArray(executionRecord?.steps) && executionRecord.steps.length > 0
      ? executionRecord.steps
      : Array.isArray(preview.executionSteps) && preview.executionSteps.length > 0
        ? preview.executionSteps
        : Array.isArray(preview.steps)
          ? preview.steps
          : []);
  return rawSteps
    .slice(0, MAX_PLAN_STEPS)
    .map((step, index) => normalizedStep(step, index, privacyClass))
    .filter((step): step is AgentTrajectoryRecord["plan"]["steps"][number] => Boolean(step));
}

function resultDigest(event: Record<string, unknown>): string | null {
  const candidate = event.output ?? event.result ?? event.data ?? event.summary;
  return candidate === undefined ? null : boundedHash(candidate);
}

function outputKind(event: Record<string, unknown>): string | null {
  const output = recordOf(event.output ?? event.result);
  return safeLabel(output?.kind ?? event.outputKind ?? event.resultKind, 80);
}

function readStateReadback(event: Record<string, unknown>): {
  observed: boolean | null;
  keys: string[];
} {
  const readback =
    recordOf(event.stateReadback) ??
    recordOf(event.stateReadBack) ??
    recordOf(recordOf(event.result)?.stateReadback) ??
    null;
  return {
    observed: readBoolean(readback, "observed", "exists", "closed", "open"),
    keys: readback
      ? Object.keys(readback)
          .filter((key) => !PRIVATE_KEY_PATTERN.test(key))
          .map((key) => safeLabel(key, 80))
          .filter((key): key is string => Boolean(key))
          .slice(0, 16)
      : [],
  };
}

function explicitErrorCode(value: unknown): string | null {
  const normalized = stringValue(value, 80)?.toUpperCase() ?? "";
  if (!normalized || !/^[A-Z][A-Z0-9_.-]{2,79}$/u.test(normalized)) return null;
  return normalized;
}

function errorCodeFromEvent(event: Record<string, unknown>): string | null {
  const direct = explicitErrorCode(event.errorCode ?? event.code);
  if (direct) return direct;
  const error = stringValue(event.error);
  const match = error?.match(/\b[A-Z][A-Z0-9_.-]{2,79}\b/u);
  return match?.[0] ?? null;
}

function eventSucceeded(event: Record<string, unknown>): boolean {
  if (typeof event.ok === "boolean") return event.ok;
  if (errorCodeFromEvent(event)) return false;
  // Older desktop/Gemini tool events carried only {tool, args, output}.
  // Treat a present output as a successful transport result; verification is
  // still independent and remains required for global training eligibility.
  return event.output !== undefined || event.result !== undefined;
}

function readToolCalls(
  result: Record<string, unknown>,
  privacyClass: string | null,
): AgentTrajectoryRecord["toolCalls"] {
  const rawEvents = readArray(result, "toolEvents", "tools", "toolCalls");
  return rawEvents
    .slice(0, MAX_TOOL_EVENTS)
    .map((raw, sequence) => {
      const event = recordOf(raw) ?? {};
      const tool = stringValue(event.tool ?? event.capability ?? event.name, 120) ?? "unknown";
      const args = sanitizeArgs(event.args ?? event.input ?? event.arguments, privacyClass);
      const readback = readStateReadback(event);
      const attempt = readNumber(event, "attempt", "retry", "retryCount");
      const latencyMs = readNumber(event, "latencyMs", "durationMs", "elapsedMs");
      return {
        sequence,
        tool,
        args: args.args,
        redactedArgKeys: args.redactedArgKeys,
        ok: eventSucceeded(event),
        verified: typeof event.verified === "boolean" ? event.verified : null,
        attempt: attempt === null ? null : Math.max(1, Math.min(100, Math.round(attempt))),
        latencyMs: latencyMs === null ? null : Math.max(0, Math.min(86_400_000, Math.round(latencyMs))),
        errorCode: errorCodeFromEvent(event),
        result: {
          contentIncluded: false,
          outputKind: outputKind(event),
          resultSha256: resultDigest(event),
          stateReadbackObserved: readback.observed,
          stateReadbackKeys: readback.keys,
        },
      };
    });
}

function readModelIdentity(
  payload: Record<string, unknown>,
  result: Record<string, unknown>,
): { provider: string | null; model: string | null; artifactVersion: string | null; decisionSource: string | null } {
  const metadata = readPayloadMetadata(payload);
  const candidates = [
    result,
    recordOf(result.metadata),
    recordOf(result.planMetadata),
    metadata,
    recordOf(metadata.model),
    recordOf(metadata.inference),
  ].filter((value): value is Record<string, unknown> => Boolean(value));
  const first = (...keys: string[]) => {
    for (const candidate of candidates) {
      const value = safeLabel(readString(candidate, ...keys), 160);
      if (value) return value;
    }
    return null;
  };
  return {
    provider: first("provider", "modelProvider", "model_provider"),
    model: first("model", "modelName", "model_name"),
    artifactVersion: first("artifactVersion", "modelArtifactVersion", "artifact_version", "artifactSha256"),
      decisionSource: first("decisionSource", "planSource", "materializationSource", "source"),
  };
}

function readVerification(
  result: Record<string, unknown>,
  toolCalls: AgentTrajectoryRecord["toolCalls"],
): AgentTrajectoryRecord["verification"] {
  const verification =
    recordOf(result.verification) ??
    recordOf(result.verificationEvidence) ??
    recordOf(result.goalVerification) ??
    recordOf(recordOf(result.executionTrace)?.verification);
  const evidence = verification
    ? readArray(verification, "evidence", "items", "rules").slice(0, 32)
    : [];
  const evidenceKinds = [
    ...safeStringList(verification?.evidenceKinds, 16),
    ...evidence.flatMap((item) => {
      const record = recordOf(item);
      return [safeLabel(record?.kind ?? record?.type ?? record?.evidence, 80) ?? ""];
    }),
  ].filter(Boolean).slice(0, 16);
  const toolVerified = toolCalls.filter((tool) => tool.verified === true).length;
  const explicit = Boolean(verification) || toolVerified > 0 || result.stateReadBackVerified === true || result.stateVerified === true;
  const statusValue = stringValue(verification?.status ?? verification?.result)?.toLowerCase();
  const status: AgentTrajectoryRecord["verification"]["status"] =
    statusValue === "passed" || statusValue === "verified" || statusValue === "success"
      ? "passed"
      : statusValue === "partial" || statusValue === "degraded"
        ? "partial"
        : statusValue === "failed" || statusValue === "error"
          ? "failed"
          : explicit && toolCalls.length > 0 && toolVerified === toolCalls.length
            ? "passed"
            : "unknown";
  return { status, evidenceKinds, evidenceCount: Math.max(evidence.length, toolVerified), explicit };
}

function readReplanning(result: Record<string, unknown>): AgentTrajectoryRecord["replanning"] {
  const trace = recordOf(result.executionTrace);
  const replan = recordOf(result.replan) ?? recordOf(result.replanning) ?? recordOf(trace?.replan) ?? null;
  const metrics = recordOf(result.loopMetrics) ?? recordOf(trace?.metrics) ?? null;
  const count = Math.max(
    0,
    Math.min(
      100,
      Math.round(
        readNumber(replan, "count", "replanCount") ??
          readNumber(metrics, "replanCount", "replans") ??
          0,
      ),
    ),
  );
  const reasons = safeStringList(replan ? readArray(replan, "reasons", "reasonCodes") : [], 8)
    .map((reason) => explicitErrorCode(reason) ?? stringValue(reason, 80))
    .filter((reason): reason is string => Boolean(reason));
  return { occurred: count > 0 || Boolean(replan), count, reasons };
}

function readErrorCodes(
  task: AgentTrajectoryInput["task"],
  result: Record<string, unknown>,
  toolCalls: AgentTrajectoryRecord["toolCalls"],
): string[] {
  const candidates = [
    explicitErrorCode(result.errorCode),
    explicitErrorCode(result.code),
    stringValue(task.error)?.match(/\b[A-Z][A-Z0-9_.-]{2,79}\b/u)?.[0] ?? null,
    ...toolCalls.map((tool) => tool.errorCode),
  ].filter((value): value is string => Boolean(value));
  return [...new Set(candidates)].slice(0, MAX_ERROR_CODES);
}

function safeOutcomeReasons(reasons: string[]): string[] {
  return reasons
    .map((reason) => {
      const normalized = stringValue(reason, 120) ?? "";
      if (!normalized) return null;
      const [prefix] = normalized.split(":", 1);
      if (prefix.toLowerCase() === "error") return "error_present";
      return /^[a-z0-9_.-]{2,100}$/iu.test(normalized) ? normalized : `reason_${sha256(normalized).slice(0, 12)}`;
    })
    .filter((reason): reason is string => Boolean(reason))
    .slice(0, 8);
}

function readApproval(
  payload: Record<string, unknown>,
  taskApprovalRequest?: unknown,
): AgentTrajectoryRecord["approval"] {
  const workOrder = readWorkOrder(payload);
  const execution = readExecutionContract(payload);
  const approval = recordOf(execution.approval) ?? {};
  const approvalRequest = recordOf(taskApprovalRequest) ?? recordOf(payload.approvalRequest) ?? {};
  const resolution = recordOf(approvalRequest.resolution) ?? {};
  const capabilities = safeStringList(
    workOrder.approvalCapabilities ??
      approval.scope ??
      approval.separateApprovalFor ??
      approvalRequest.capabilities ??
      approvalRequest.capability,
    32,
  );
  const required =
    approval.required === true ||
    workOrder.requiresApproval === true ||
    capabilities.length > 0 ||
    Object.keys(approvalRequest).length > 0;
  const approved = resolution.approved === true || ["approved", "accepted", "confirmed"].includes(String(resolution.status ?? "").toLowerCase());
  const rejected = resolution.approved === false || ["rejected", "denied", "declined"].includes(String(resolution.status ?? "").toLowerCase());
  return {
    required,
    capabilities,
    decision: approved ? "approved" : rejected ? "rejected" : required ? "unknown" : "not_required",
  };
}

function readRuntimeSnapshot(
  payload: Record<string, unknown>,
  route: Record<string, unknown>,
  task: AgentTrajectoryInput["task"],
): AgentTrajectoryRecord["platform"] {
  const metadata = readPayloadMetadata(payload);
  const snapshot =
    recordOf(metadata.runtimeCapabilitySnapshot) ??
    recordOf(metadata.runtimeSnapshot) ??
    recordOf(payload.runtimeCapabilitySnapshot) ??
    {};
  const platform = safePlatform(snapshot.platform ?? metadata.platform ?? route.platform);
  const routeName = stringValue(route.route);
  const targetKind = targetKindFromPlatform(platform, routeName);
  return {
    targetKind,
    platform,
    targetDeviceIdSha256: task.targetDeviceId ? sha256(task.targetDeviceId) : null,
    onlineAtAdmission: readBoolean(snapshot, "online", "isOnline", "canReceiveTasks"),
    liveCapabilities: safeStringList(
      snapshot.capabilities ?? metadata.liveCapabilities ?? metadata.runtimeCapabilities,
      MAX_CAPABILITIES,
    ),
  };
}

function readPrivacyClass(payload: Record<string, unknown>): string | null {
  const workOrder = readWorkOrder(payload);
  const preview = recordOf(workOrder.planPreview) ?? recordOf(payload.planPreview);
  return stringValue(preview?.privacyClass) ?? stringValue(workOrder.privacyClass);
}

function readPrompt(task: AgentTrajectoryInput["task"], payload: Record<string, unknown>): string {
  return (typeof payload.prompt === "string" ? payload.prompt : "")
    .trim() || String(task.title ?? "").trim();
}

function readPlanSource(payload: Record<string, unknown>): string | null {
  const workOrder = readWorkOrder(payload);
  const preview = recordOf(workOrder.planPreview) ?? recordOf(payload.planPreview);
  return safeLabel(preview?.materializationSource ?? preview?.planSource ?? workOrder.executionPlan);
}

function readPlanRevision(payload: Record<string, unknown>): number | null {
  const contract = readExecutionContract(payload);
  const value = readNumber(contract, "planRevision");
  return value === null ? null : Math.max(1, Math.min(10_000, Math.round(value)));
}

function trainingEligible(
  verdict: AgentTrajectoryVerdict,
  verification: AgentTrajectoryRecord["verification"],
  toolCalls: AgentTrajectoryRecord["toolCalls"],
  approval: AgentTrajectoryRecord["approval"],
): boolean {
  if (verdict === "unfulfilled") return false;
  if (!verification.explicit || verification.status !== "passed") return false;
  if (verification.evidenceCount <= 0) return false;
  if (approval.required && approval.decision !== "approved") return false;
  return toolCalls.length === 0 || toolCalls.every((tool) => tool.ok && tool.verified !== false);
}

export function buildAgentTrajectoryRecord(input: AgentTrajectoryInput): AgentTrajectoryRecord {
  const payload = readPayloadRoot(input.task);
  const metadata = readPayloadMetadata(payload);
  const route = readRouteDecision(payload, metadata);
  const workOrder = readWorkOrder(payload);
  const contract = readExecutionContract(payload);
  const result = readResultRecord(input);
  const prompt = readPrompt(input.task, payload);
  const privacyClass = readPrivacyClass(payload);
  const toolCalls = readToolCalls(result, privacyClass);
  const verification = readVerification(result, toolCalls);
  const modelIdentity = readModelIdentity(payload, result);
  const runtimeSnapshot = readRuntimeSnapshot(payload, route, input.task);
  const requiredCapabilities = safeStringList(
    route.capabilities ??
      recordOf(route.taskRoute)?.requiredCapabilities ??
      workOrder.requiredCapabilities ??
      recordOf(contract.execution)?.selectedTools,
    MAX_CAPABILITIES,
  );
  const routeTarget =
    stringValue(recordOf(route.taskRoute)?.target) ??
    stringValue(route.targetDevice) ??
    stringValue(route.route);
  const confidence = readNumber(route, "confidence");
  const normalizedConfidence = confidence === null ? null : Math.max(0, Math.min(1, confidence));
  const missingInformation =
    stringValue(route.missingInformation ?? route.missing_information) ??
    stringValue(recordOf(contract.goal)?.missingInformation);
  const retryCount = Math.max(
    0,
    Math.min(
      100,
      Math.max(
        ...toolCalls.map((tool) => Math.max(0, (tool.attempt ?? 1) - 1)),
        readNumber(result, "retryCount", "retries") ?? 0,
      ),
    ),
  );
  const latencyMs =
    input.latencyMs ??
    readNumber(result, "latencyMs", "durationMs", "totalMs") ??
    (() => {
      const created = input.task.createdAt ? new Date(input.task.createdAt).getTime() : NaN;
      const completed = input.task.completedAt ? new Date(input.task.completedAt).getTime() : NaN;
      return Number.isFinite(created) && Number.isFinite(completed) && completed >= created
        ? completed - created
        : null;
    })();
  const approval = readApproval(payload, input.task.approvalRequest);
  const verificationTrainingEligible = trainingEligible(
    input.assessment.verdict,
    verification,
    toolCalls,
    approval,
  );
  return {
    contract: AGENT_TRAJECTORY_CONTRACT,
    version: 1,
    episodeId: agentTrajectoryEpisodeId(input.task.id),
    taskId: input.task.id,
    request: {
      contentIncluded: false,
      summary: "redacted",
      sha256: boundedHash(prompt),
      lengthBucket: lengthBucket(prompt),
      language: languageFor(prompt),
    },
    platform: runtimeSnapshot,
    modelDecision: {
      route: safeLabel(route.route),
      intent: safeLabel(route.intent),
      targetDevice: safeLabel(routeTarget),
      confidence: normalizedConfidence,
      requiredCapabilities,
      missingInformation: {
        present: Boolean(missingInformation),
        sha256: missingInformation ? boundedHash(missingInformation) : null,
      },
      requiresConfirmation:
        route.requiresApproval === true || route.requiresConfirmation === true || route.shouldAskClarification === true,
      goalContract: readGoalContract(workOrder, contract),
      provider: modelIdentity.provider,
      model: modelIdentity.model,
      artifactVersion: modelIdentity.artifactVersion,
      decisionSource: modelIdentity.decisionSource,
    },
    plan: {
      source: readPlanSource(payload),
      revision: readPlanRevision(payload),
      steps: readPlanSteps(payload, privacyClass),
    },
    toolCalls,
    approval,
    verification,
    replanning: readReplanning(result),
    outcome: {
      verdict: input.assessment.verdict,
      reasons: safeOutcomeReasons(input.assessment.reasons),
    },
    telemetry: {
      latencyMs: latencyMs === null ? null : Math.max(0, Math.min(86_400_000, Math.round(latencyMs))),
      retryCount,
      errorCodes: readErrorCodes(input.task, result, toolCalls),
    },
    privacy: {
      rawPromptIncluded: false,
      rawToolResultsIncluded: false,
      rawToolArgsIncluded: false,
      redaction: "hash_only_default",
      trainingEligible: verificationTrainingEligible,
      preferenceScope: "user",
    },
  };
}

/**
 * Terminal görev geçişinde tek trajectory satırı yaz. Unique(task,type,key)
 * ve ON CONFLICT ile eşzamanlı lifecycle tekrarları idempotent kalır.
 */
export async function recordAgentTrajectory(
  app: FastifyInstance,
  input: AgentTrajectoryInput,
): Promise<boolean> {
  const record = buildAgentTrajectoryRecord(input);
  try {
    await app.db
      .insert(learningEvents)
      .values({
        userId: input.task.userId,
        accountId: input.task.userId,
        taskId: input.task.id,
        type: AGENT_TRAJECTORY_EVENT_TYPE,
        key: AGENT_TRAJECTORY_EVENT_KEY,
        value: `${record.outcome.verdict}:${record.episodeId}`,
        confidence:
          record.outcome.verdict === "fulfilled"
            ? 100
            : record.outcome.verdict === "degraded"
              ? 60
              : 0,
        scope: "user",
        source: "runtime",
        privacyLevel: "safe",
        // Continuous-learning filtresi geriye dönük olarak top-level
        // `metadata.trainingEligible` okur; nested privacy kaydı da aynı
        // bilgiyi taşıyarak trajectory şemasını kendi başına açıklanabilir
        // bırakır.
        metadata: {
          ...record,
          trainingEligible: record.privacy.trainingEligible,
          globalTrainingEligible: record.privacy.trainingEligible,
        },
      })
      .onConflictDoNothing();
    // TİPLİ AMBARA İKİNCİ YAZIM.
    //
    // Yukarıdaki satır `learning_events` içindir ve öyle kalır: mevcut
    // tüketiciler (continuous-learning filtresi, redaksiyon) oradan okuyor.
    // Ama o tablo GERİ ÇAĞRILAMIYOR — düz metin eşlemesinden ötesi yok. Aynı
    // epizot burada tipli satıra ve gömmeye de yazılır ki "bu isteğe benzer
    // daha önce ne yaptım?" sorusu cevaplanabilsin.
    //
    // Fail-open: epizot ambarı öğrenme içindir, yürütme değil.
    await recordTaskEpisode(app, {
      userId: input.task.userId,
      taskId: input.task.id,
      record,
      requestText: readPrompt(input.task, recordOf(input.task.payload) ?? {}),
    });
    return true;
  } catch (error) {
    app.log?.warn?.(
      { err: error instanceof Error ? error.message : String(error), taskId: input.task.id },
      "agent trajectory not recorded",
    );
    return false;
  }
}

/**
 * Kullanıcı unutma/redaksiyon isteği için trajectory'yi eğitim havuzundan da
 * çıkarır. Satır fiziksel olarak tutulsa bile restricted + expired + tombstone
 * işaretleri continuous-learning filtresinin tamamını kapatır.
 */
export async function redactAgentTrajectoryRecords(
  db: FastifyInstance["db"],
  input: { userId: string; taskId?: string | null; now?: Date; reason?: string },
): Promise<void> {
  const now = input.now ?? new Date();
  const baseFilters = [
    eq(learningEvents.userId, input.userId),
  ];
  const taskFilter = input.taskId
    ? eq(learningEvents.taskId, input.taskId)
    : sql`true`;
  const linkedTrajectoryOrToolOutcome = or(
    and(
      eq(learningEvents.type, AGENT_TRAJECTORY_EVENT_TYPE),
      eq(learningEvents.key, AGENT_TRAJECTORY_EVENT_KEY),
    ),
    and(
      eq(learningEvents.type, "tool_outcome"),
      sql`${learningEvents.metadata}->>'episodeId' is not null`,
    ),
  );
  const redactionMetadata = {
    redacted: true,
    tombstone: true,
    forgotten: true,
    trainingEligible: false,
    redactionReason: stringValue(input.reason, 120) ?? "explicit_user_forget",
    redactedAt: now.toISOString(),
  };
  // Insert the tombstone before updating existing rows. The unique task/type/
  // key constraint then makes a concurrent terminal writer wait and no-op,
  // whether the trajectory already existed or not.
  if (input.taskId) {
    await db
      .insert(learningEvents)
      .values({
        userId: input.userId,
        taskId: input.taskId,
        type: AGENT_TRAJECTORY_EVENT_TYPE,
        key: AGENT_TRAJECTORY_EVENT_KEY,
        value: `forgotten:${agentTrajectoryEpisodeId(input.taskId)}`,
        confidence: 0,
        scope: "user",
        source: "system",
        privacyLevel: "restricted",
        metadata: {
          contract: AGENT_TRAJECTORY_CONTRACT,
          episodeId: agentTrajectoryEpisodeId(input.taskId),
          ...redactionMetadata,
        },
        expiresAt: now,
      })
      .onConflictDoNothing();
  }

  await db
    .update(learningEvents)
    .set({
      privacyLevel: "restricted",
      expiresAt: now,
      metadata: sql`${learningEvents.metadata} || ${JSON.stringify(redactionMetadata)}::jsonb`,
    })
    .where(and(...baseFilters, taskFilter, linkedTrajectoryOrToolOutcome));

  // TİPLİ AMBAR DA UNUTMALI.
  //
  // Unutma isteği yalnız `learning_events` satırını kapatsaydı, epizot
  // ambarındaki gömme geri çağırma havuzunda kalmaya devam ederdi — kullanıcı
  // "unut" dedikten sonra bile o epizot benzer isteklerde emsal olarak
  // çıkardı. Gömme ve adım şekli fiziksel olarak silinir; satır denetim için
  // kalır ama öğrenmeye kapanır.
  await db
    .update(taskEpisodes)
    .set({
      trainingEligible: false,
      requestEmbedding: null,
      embeddingModel: null,
      stepShapes: [],
      contractDigest: null,
    })
    .where(
      and(
        eq(taskEpisodes.userId, input.userId),
        input.taskId ? eq(taskEpisodes.taskId, input.taskId) : sql`true`,
      ),
    );
}
