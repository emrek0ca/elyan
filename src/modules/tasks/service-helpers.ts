import type { TaskStatus } from "../../contracts/domain.js";
import { createIdempotencyFingerprint } from "../../lib/idempotency.js";
import { AppError, unprocessableEntity } from "../../lib/errors.js";
import { normalizeLocalDerivedMetadata } from "../../lib/derived-data.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "./desktop-capability-manifest.js";
import { DESKTOP_SKILL_MANIFEST } from "./desktop-skill-manifest.js";

type IdempotentTaskRow = {
  id: string;
  idempotencyFingerprint: string | null;
};

export type MobileTaskFeedRow = {
  id: string;
  title: string;
  status: TaskStatus;
  targetDeviceId: string;
  queuePosition: number;
  dispatchAttemptCount?: number | null;
  runtimeConnectionId?: string | null;
  dispatchLeaseId?: string | null;
  dispatchLeaseIssuedAt?: Date | null;
  dispatchLeaseExpiresAt?: Date | null;
  dispatchAckAt?: Date | null;
  requestedCapabilities?: unknown;
  payload?: unknown;
  result?: unknown;
  summary?: string | null;
  error?: string | null;
  approvalRequest?: unknown;
  createdAt: Date;
  startedAt?: Date | null;
  completedAt?: Date | null;
  canceledAt?: Date | null;
  updatedAt: Date;
};

export type OwnedDesktopTaskTarget = {
  type: "mobile" | "desktop";
  isActive: boolean;
  canReceiveTasks: boolean;
  isOnline: boolean;
  targetStatus: string;
  runtime: {
    lastHeartbeatAt: Date | null;
  };
};

export type SharedBrainConversationMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

export type TaskDeliveryState =
  "queued" | "dispatched" | "acked" | "recovering";
export type TaskArtifactViewerHint =
  "text" | "markdown" | "pdf" | "image" | "document" | "structured" | "file";
export type TaskArtifactContentFamily =
  "text" | "image" | "document" | "structured" | "binary";
export type TaskArtifactRecord = {
  id: string;
  taskId: string;
  kind: string;
  name: string;
  contentType: string;
  storageKey?: string | null;
  textContent?: string | null;
  payload?: unknown;
  bodyBlobId?: string | null;
  contentHash?: string | null;
  byteLength?: number | null;
  contentEncoding?: string | null;
  downloadable?: boolean | null;
  viewerHint?: string | null;
  downloadUrl?: string | null;
  metadata?: unknown;
  createdAt: Date;
};
export type ShapedTaskArtifact = TaskArtifactRecord & {
  viewerHint: TaskArtifactViewerHint;
  contentFamily: TaskArtifactContentFamily;
  previewText: string | null;
  downloadName: string;
  downloadable: boolean;
  downloadUrl: string | null;
  contentHash: string | null;
  byteLength: number | null;
  contentEncoding: string | null;
};

const TASK_TITLE_MAX_LENGTH = 96;
const TASK_TITLE_FALLBACK = "Yeni görev";

function normalizeTaskTitle(raw: unknown): string {
  const text = String(raw ?? "")
    .replace(/\s+/g, " ")
    .trim();

  if (!text) {
    return "";
  }

  if (text.length <= TASK_TITLE_MAX_LENGTH) {
    return text;
  }

  return `${text.slice(0, TASK_TITLE_MAX_LENGTH - 1).trimEnd()}…`;
}

export function canonicalTaskTitle(input: {
  title?: unknown;
  prompt?: unknown;
}): string {
  return (
    normalizeTaskTitle(input.title) ||
    normalizeTaskTitle(input.prompt) ||
    TASK_TITLE_FALLBACK
  );
}

export function shapeTaskFeedItem(
  task: MobileTaskFeedRow,
  options?: {
    selectedDesktopOnline?: boolean | null;
  },
) {
  const quantum = extractTaskQuantumSnapshot(task);
  const presentation = extractTaskPresentation(task.payload);
  const routeDecision = extractTaskRouteDecision(task.payload);
  const runtimeAcceptance = extractTaskRuntimeAcceptance(task.payload);
  const desktopHandoff = extractTaskDesktopHandoff(task.payload);
  const planningEvidence = extractTaskPlanningEvidence(task.payload);
  const supersedesTaskId = extractTaskSupersedesTaskId(task.payload);
  const operator = extractTaskOperatorSummary(task.result);
  const brain = extractTaskBrainMetadata(task.result);
  const resultRecord =
    task.result &&
    typeof task.result === "object" &&
    !Array.isArray(task.result)
      ? (task.result as Record<string, unknown>)
      : null;
  const renderRecipe =
    resultRecord?.renderRecipe &&
    typeof resultRecord.renderRecipe === "object" &&
    !Array.isArray(resultRecord.renderRecipe)
      ? resultRecord.renderRecipe
      : null;
  return {
    id: task.id,
    title: canonicalTaskTitle({ title: task.title }),
    status: task.status,
    targetDeviceId: task.targetDeviceId,
    chatSessionId: extractTaskChatSessionId(task.payload),
    supersedesTaskId,
    presentation,
    queuePosition: task.queuePosition,
    requestedCapabilities: Array.isArray(task.requestedCapabilities)
      ? task.requestedCapabilities
      : [],
    runtimeConnectionId: task.runtimeConnectionId ?? null,
    dispatchLeaseId: task.dispatchLeaseId ?? null,
    dispatchLeaseExpiresAt: task.dispatchLeaseExpiresAt ?? null,
    dispatchAckAt: task.dispatchAckAt ?? null,
    lastAckAt: task.dispatchAckAt ?? null,
    deliveryAttemptCount: task.dispatchAttemptCount ?? 0,
    lastDispatchAttemptAt:
      task.dispatchLeaseIssuedAt ?? task.dispatchAckAt ?? null,
    deliveryState: deriveTaskDeliveryState(task),
    selectedDesktopOnline: options?.selectedDesktopOnline ?? null,
    routeDecision,
    ...(runtimeAcceptance ? { runtimeAcceptance } : {}),
    ...(desktopHandoff ? { desktopHandoff } : {}),
    ...(planningEvidence ? { planningEvidence } : {}),
    ...(brain ? { brain } : {}),
    ...(operator ? { operator } : {}),
    ...(quantum ? { quantum } : {}),
    ...(renderRecipe ? { renderRecipe } : {}),
    summary: task.summary ?? null,
    error: task.error ?? null,
    approvalRequest: sanitizePublicInferenceValue(task.approvalRequest ?? null),
    createdAt: task.createdAt,
    startedAt: task.startedAt ?? null,
    completedAt: task.completedAt ?? null,
    canceledAt: task.canceledAt ?? null,
    updatedAt: task.updatedAt,
  };
}

function extractTaskRuntimeAcceptance(payloadValue: unknown) {
  const metadata = readRecord(readRecord(payloadValue)?.metadata);
  const acceptance = readRecord(metadata?.runtimeAcceptance);
  if (acceptance?.contract !== "elyan.runtime_task_acceptance.v1") {
    return null;
  }
  return sanitizePublicInferenceValue({
    contract: readString(acceptance, "contract"),
    state: readString(acceptance, "state"),
    missingCapabilities: readStringList(acceptance, "missingCapabilities"),
    blockedReason: readString(acceptance, "blockedReason"),
    consumedContractFields: readStringList(
      acceptance,
      "consumedContractFields",
    ),
    acceptedAt: readString(acceptance, "acceptedAt"),
  });
}

function extractTaskDesktopHandoff(payloadValue: unknown) {
  const payload = readRecord(payloadValue);
  const workOrder = readRecord(payload?.desktopWorkOrder);
  if (!workOrder) {
    return null;
  }

  const schema = readString(workOrder, "schema");
  if (schema !== "elyan.desktop_work_order.v1") {
    return null;
  }

  const semanticGoal = readRecord(workOrder.semanticGoal);
  const planPreview = readRecord(workOrder.planPreview);
  const planPreparation = readRecord(planPreview?.planPreparation);
  const executionPlan = readRecord(workOrder.executionPlan);
  const verificationPlan = readRecord(workOrder.verificationPlan);
  const expectedOutput = readRecord(workOrder.expectedOutput);
  const liveNarrationPlan = readRecord(planPreview?.liveNarrationPlan);
  const rawSteps = Array.isArray(planPreview?.steps)
    ? planPreview.steps.slice(0, 16)
    : [];

  const stepCapabilities = rawSteps
    .map((step) => readString(readRecord(step), "capability"))
    .filter((capability): capability is string => Boolean(capability));

  return sanitizePublicInferenceValue({
    schema,
    contract: readString(semanticGoal, "contract"),
    workType: readString(workOrder, "workType"),
    privacyClass: readString(workOrder, "privacyClass"),
    executionMode: readString(executionPlan, "mode"),
    status: readString(planPreparation, "status") ?? "pending",
    planSource: readString(planPreview, "planSource"),
    requiresApproval: readBoolean(workOrder, "requiresApproval"),
    requiresArtifact: readBoolean(expectedOutput, "requiresArtifact"),
    verificationRequiresEvidence: readBoolean(
      verificationPlan,
      "requireEvidence",
    ),
    requiredCapabilities: readStringList(workOrder, "requiredCapabilities"),
    stepCapabilities,
    narrationMode: readString(liveNarrationPlan, "mode"),
    narrationUpdatePolicy: readString(liveNarrationPlan, "updatePolicy"),
  });
}

const PUBLIC_CAPABILITY_BY_NAME = new Map(
  DESKTOP_CAPABILITY_MANIFEST.map((entry) => [entry.name, entry] as const),
);
const PUBLIC_SKILL_BY_ID = new Map(
  DESKTOP_SKILL_MANIFEST.map((entry) => [entry.id, entry] as const),
);

function extractTaskPlanningEvidence(payloadValue: unknown) {
  const payload = readRecord(payloadValue);
  const workOrder = readRecord(payload?.desktopWorkOrder);
  const planPreview = readRecord(workOrder?.planPreview);
  if (
    !planPreview ||
    readString(planPreview, "planSource") !== "server_materialized" ||
    readString(planPreview, "contract") !== "elyan.compiled_plan.v1"
  ) {
    return null;
  }

  const rawSteps = Array.isArray(planPreview.steps)
    ? planPreview.steps.slice(0, 16)
    : [];
  const capabilities = new Set<string>();
  const skills = new Set<string>();
  const privacyClasses = new Set<string>();
  let approvalStepCount = 0;

  for (const rawStep of rawSteps) {
    const step = readRecord(rawStep);
    const capabilityName = readString(step, "capability");
    const capability = capabilityName
      ? PUBLIC_CAPABILITY_BY_NAME.get(capabilityName)
      : null;
    if (!capability) continue;
    capabilities.add(capability.name);
    privacyClasses.add(capability.privacyClass);

    let requiresApproval = capability.requiresApproval;
    if (capability.name === "run_skill") {
      const args = readRecord(step?.args);
      const skillId = readString(args, "skillId");
      const skill = skillId ? PUBLIC_SKILL_BY_ID.get(skillId) : null;
      if (skill) {
        skills.add(skill.id);
        requiresApproval ||= skill.requiresConfirmation;
      }
    }
    if (requiresApproval) approvalStepCount += 1;
  }

  if (capabilities.size === 0) return null;
  const preparation = readRecord(planPreview.planPreparation);
  const status = readString(preparation, "status");
  return {
    source: "server_materialized",
    contract: "elyan.compiled_plan.v1",
    status: status === "failed" ? "failed" : "ready",
    stepCount: rawSteps.length,
    capabilities: [...capabilities],
    skills: [...skills],
    approvalStepCount,
    privacyClasses: [...privacyClasses],
  };
}

export function shapeTaskArtifact<T extends TaskArtifactRecord>(
  artifact: T,
): T & ShapedTaskArtifact {
  const viewerHint =
    typeof artifact.viewerHint === "string" && artifact.viewerHint.trim()
      ? (artifact.viewerHint.trim() as TaskArtifactViewerHint)
      : inferArtifactViewerHint(artifact.kind, artifact.contentType);
  const previewText = extractArtifactPreviewText(artifact);
  return {
    ...artifact,
    downloadName: normalizeArtifactName(artifact.name) || artifact.id,
    downloadable: Boolean(
      artifact.downloadable ?? artifact.storageKey ?? artifact.bodyBlobId,
    ),
    downloadUrl:
      typeof artifact.downloadUrl === "string" && artifact.downloadUrl.trim()
        ? artifact.downloadUrl
        : null,
    contentHash:
      typeof artifact.contentHash === "string" && artifact.contentHash.trim()
        ? artifact.contentHash
        : null,
    byteLength:
      typeof artifact.byteLength === "number" &&
      Number.isFinite(artifact.byteLength)
        ? artifact.byteLength
        : null,
    contentEncoding:
      typeof artifact.contentEncoding === "string" &&
      artifact.contentEncoding.trim()
        ? artifact.contentEncoding.trim()
        : null,
    viewerHint,
    contentFamily: inferArtifactContentFamily(viewerHint),
    previewText,
  };
}

function inferArtifactViewerHint(
  kind: string,
  contentType: string,
): TaskArtifactViewerHint {
  const normalizedKind = String(kind ?? "")
    .trim()
    .toLowerCase();
  const mime = normalizeMimeType(contentType);

  if (
    normalizedKind === "markdown" ||
    mime === "text/markdown" ||
    mime.endsWith("+markdown")
  ) {
    return "markdown";
  }

  if (normalizedKind === "screenshot" || mime.startsWith("image/")) {
    return "image";
  }

  if (mime === "application/pdf") {
    return "pdf";
  }

  if (
    mime.includes("wordprocessingml") ||
    mime.includes("msword") ||
    mime.includes("officedocument") ||
    mime.includes("opendocument.text") ||
    mime === "application/rtf"
  ) {
    return "document";
  }

  if (
    normalizedKind === "structured_output" ||
    mime === "application/json" ||
    mime.endsWith("+json") ||
    mime === "application/xml" ||
    mime.endsWith("+xml") ||
    mime === "text/csv"
  ) {
    return "structured";
  }

  if (normalizedKind === "summary" || mime.startsWith("text/")) {
    return "text";
  }

  return "file";
}

function inferArtifactContentFamily(
  viewerHint: TaskArtifactViewerHint,
): TaskArtifactContentFamily {
  switch (viewerHint) {
    case "image":
      return "image";
    case "pdf":
    case "document":
      return "document";
    case "markdown":
    case "text":
      return "text";
    case "structured":
      return "structured";
    case "file":
    default:
      return "binary";
  }
}

function extractArtifactPreviewText(
  artifact: TaskArtifactRecord,
): string | null {
  const textContent = normalizePreviewSource(artifact.textContent);
  if (textContent) {
    return compactPreviewText(textContent);
  }

  const payload = readRecord(artifact.payload);
  const outputType = readString(payload, "output_type");
  const format = readString(payload, "format");
  const payloadPreview =
    (outputType && format ? `${outputType} (${format})` : null) ??
    readString(payload, "previewText") ??
    readString(payload, "summary") ??
    readString(payload, "textContent") ??
    readString(payload, "text") ??
    readString(payload, "content");
  if (!payloadPreview) {
    return null;
  }

  return compactPreviewText(payloadPreview);
}

function compactPreviewText(text: string, maxLength = 320): string {
  const normalized = normalizePreviewSource(text);
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function normalizePreviewSource(value: unknown): string {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function normalizeMimeType(contentType: string): string {
  return (
    String(contentType ?? "")
      .trim()
      .toLowerCase()
      .split(";")[0]
      ?.trim() ?? ""
  );
}

function normalizeArtifactName(name: string): string {
  return String(name ?? "")
    .replace(/\s+/g, " ")
    .trim();
}

function extractToolFlowSummary(result: Record<string, unknown>) {
  const record = readRecord(result.toolFlow);
  if (!record) {
    return null;
  }
  const rawTools = Array.isArray(record.tools) ? record.tools : [];
  const tools: Array<{
    name: string;
    ok: boolean;
    resultCount: number | null;
  }> = [];
  let derivedOkCount = 0;
  for (const item of rawTools) {
    const toolRecord = readRecord(item);
    const name =
      readString(toolRecord, "name") ?? readString(toolRecord, "tool");
    if (!name) {
      continue;
    }
    const ok = readBoolean(toolRecord, "ok") === true;
    if (ok) {
      derivedOkCount += 1;
    }
    tools.push({
      name,
      ok,
      resultCount: readNumber(toolRecord, "resultCount"),
    });
    if (tools.length >= 8) {
      break;
    }
  }
  if (tools.length === 0) {
    return null;
  }
  const declaredOkCount = readNumber(record, "okCount");
  return {
    count: tools.length,
    okCount: declaredOkCount != null ? declaredOkCount : derivedOkCount,
    tools,
  };
}

function extractConnectorWriteApproval(result: Record<string, unknown>) {
  const record = readRecord(result.connectorWriteApproval);
  if (!record) {
    return null;
  }
  const token = readString(record, "token");
  const tool = readString(record, "tool");
  const title = readString(record, "title");
  if (!token || !tool || !title) {
    return null;
  }
  const rawLines = Array.isArray(record.lines) ? record.lines : [];
  const lines = rawLines
    .map((item) => {
      const line = readRecord(item);
      const label = readString(line, "label");
      const value = readString(line, "value");
      return label && value ? { label, value } : null;
    })
    .filter((item): item is { label: string; value: string } => item != null)
    .slice(0, 8);
  return {
    token,
    tool,
    title,
    appLabel: readString(record, "appLabel") ?? "",
    expiresAt: readNumber(record, "expiresAt"),
    lines,
  };
}

function extractTaskBrainMetadata(value: unknown) {
  const result = readRecord(value);
  if (!result) {
    return null;
  }
  const toolFlow = extractToolFlowSummary(result);
  const connectorWriteApproval = extractConnectorWriteApproval(result);
  const metadata = {
    firstDeltaMs: readNumber(result, "firstDeltaMs"),
    groundingUsed: readBoolean(result, "groundingUsed"),
    documentSourceCount: readNumber(result, "documentSourceCount"),
    webGroundingUsed: readBoolean(result, "webGroundingUsed"),
    webSourceCount: readNumber(result, "webSourceCount"),
    attachmentContextUsed: readBoolean(result, "attachmentContextUsed"),
    attachmentContextSource: readString(result, "attachmentContextSource"),
    attachmentDocumentIds: readStringList(result, "attachmentDocumentIds"),
    skillUsed: readBoolean(result, "skillUsed"),
    skillId: readPublicSkillId(result),
    retrievalResultCount: readNumber(result, "retrievalResultCount"),
    qualityPolicyApplied: readBoolean(result, "qualityPolicyApplied"),
    dataGroundingLevel: readString(result, "dataGroundingLevel"),
    personalizationScope: readString(result, "personalizationScope"),
    responseLanguage: readString(result, "responseLanguage"),
    evidenceSufficiency: readString(result, "evidenceSufficiency"),
    dataConfidence: readString(result, "dataConfidence"),
    dataQualityWarnings: readStringList(result, "dataQualityWarnings"),
    responseBudgetState: readString(result, "responseBudgetState"),
    responseBudgetReason: readString(result, "responseBudgetReason"),
    contextPacketCount: readNumber(result, "contextPacketCount"),
    contextPacketKinds: readStringList(result, "contextPacketKinds"),
    healthContextUsed: readBoolean(result, "healthContextUsed"),
    toolFlow,
    connectorWriteApproval,
  };
  return Object.values(metadata).some((value) =>
    Array.isArray(value) ? value.length > 0 : value !== null,
  )
    ? metadata
    : null;
}

const INTERNAL_INFERENCE_KEYS = new Set([
  "agentPlan",
  "agentplan",
  "agentRunState",
  "agentrunstate",
  "analysis",
  "provider",
  "model",
  "baseModel",
  "configuredBaseModel",
  "resolvedBaseModel",
  "resolvedBaseModelSource",
  "availableModels",
  "fallbackModel",
  "fallbackState",
  "fallbackUsed",
  "runtimeProvider",
  "activeSharedModelProvider",
  "attemptedModels",
  "attemptedProviders",
  "debug",
  "debugPayload",
  "debugpayload",
  "developerMessage",
  "developermessage",
  "internal",
  "internalMetadata",
  "internalmetadata",
  "raw",
  "rawProviderResponse",
  "rawproviderresponse",
  "reasoning",
  "reasoningTrace",
  "reasoningtrace",
  "routeDecision",
  "routedecision",
  "selectedWorkload",
  "selectedworkload",
  "stackTrace",
  "stacktrace",
  "systemPrompt",
  "systemprompt",
  "toolRequests",
  "toolrequests",
  "toolResults",
  "connectorWriteApprovalRequest",
  "connectorCall",
  "pendingCall",
  "toolresults",
  "toolTrace",
  "tooltrace",
  "modelSource",
  "modelProfile",
  "selectedProfile",
  "answerSource",
  "modelCallCount",
  "reasoningPasses",
  "dedupedInflight",
  "cheapSocialTurn",
  "cloudVisionOptIn",
  "visionEscalation",
  "visionEscalationAttempted",
  "visionEscalationUsed",
  "visionEscalationReasons",
  "visionEscalationCapacitySkipped",
  "agentEngineVersion",
  "visionBlock",
  "visionblock",
  "runtimePlan",
]);

function normalizePublicInferenceKey(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

const NORMALIZED_INTERNAL_INFERENCE_KEYS = new Set(
  [...INTERNAL_INFERENCE_KEYS].map((key) => normalizePublicInferenceKey(key)),
);

const INTERNAL_EVENT_PAYLOAD_KEYS = new Set([
  "analysis",
  "provider",
  "model",
  "baseModel",
  "configuredBaseModel",
  "resolvedBaseModel",
  "resolvedBaseModelSource",
  "availableModels",
  "fallbackModel",
  "fallbackState",
  "fallbackUsed",
  "runtimeProvider",
  "activeSharedModelProvider",
  "attemptedModels",
  "attemptedProviders",
  "debug",
  "debugPayload",
  "developerMessage",
  "internal",
  "internalMetadata",
  "raw",
  "rawProviderResponse",
  "reasoning",
  "reasoningTrace",
  "runtimePlan",
  "stackTrace",
  "systemPrompt",
  "toolRequests",
  "toolResults",
  "toolTrace",
  "modelSource",
  "modelProfile",
  "selectedProfile",
  "answerSource",
  "modelCallCount",
  "reasoningPasses",
  "dedupedInflight",
  "cheapSocialTurn",
  "cloudVisionOptIn",
  "visionEscalation",
  "visionEscalationAttempted",
  "visionEscalationUsed",
  "visionEscalationReasons",
  "visionEscalationCapacitySkipped",
  "agentEngineVersion",
  "visionBlock",
  "visionblock",
]);

const NORMALIZED_INTERNAL_EVENT_PAYLOAD_KEYS = new Set(
  [...INTERNAL_EVENT_PAYLOAD_KEYS].map((key) =>
    normalizePublicInferenceKey(key),
  ),
);

function isInternalInferenceKey(
  key: string,
  internalKeys: Set<string>,
): boolean {
  const normalized = normalizePublicInferenceKey(key);
  if (internalKeys.has(key) || internalKeys.has(normalized)) return true;
  return /(?:provider|model|engine|apikey|credential|secret|systemprompt|reasoningtrace|tooltrace|visionblock)$/u.test(
    normalized,
  );
}

function clipPublicString(value: string, maxLength: number): string {
  // Preserve markdown/newline structure; the public boundary only needs a
  // deterministic size cap, not prose normalization.
  const normalized = value.trim();
  return normalized.length <= maxLength
    ? normalized
    : `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function sanitizePublicModelRoute(
  value: unknown,
): Record<string, unknown> | null {
  const route = readRecord(value);
  if (!route) return null;
  const provider = readString(route, "provider");
  const modelFamily = readString(route, "modelFamily");
  const workload = readString(route, "workload");
  const privacyGate = readString(route, "privacyGate");
  return {
    ...(provider ? { provider } : {}),
    ...(modelFamily ? { modelFamily } : {}),
    ...(workload ? { workload } : {}),
    compoundUsed: Boolean(route.compoundUsed),
    ...(privacyGate ? { privacyGate } : {}),
    fallbackUsed: Boolean(route.fallbackUsed),
  };
}

function sanitizeBoundedPublicJson(
  value: unknown,
  internalKeys: Set<string>,
  depth = 0,
): unknown {
  if (
    value == null ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "string") {
    return clipPublicString(value, 8_000);
  }
  if (typeof value !== "object") {
    return null;
  }
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value.toISOString();
  }
  if (depth >= 8) {
    return null;
  }
  if (Array.isArray(value)) {
    return value
      .slice(0, 200)
      .map((item) => sanitizeBoundedPublicJson(item, internalKeys, depth + 1));
  }

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !isInternalInferenceKey(key, internalKeys))
      .slice(0, 80)
      .map(([key, nestedValue]) => {
        if (normalizePublicInferenceKey(key) === "modelroute") {
          return [key, sanitizePublicModelRoute(nestedValue)];
        }
        if (
          normalizePublicInferenceKey(key) === "blocks" &&
          Array.isArray(nestedValue)
        ) {
          nestedValue = nestedValue.filter((block) => {
            if (!block || typeof block !== "object" || Array.isArray(block))
              return true;
            const type = String((block as Record<string, unknown>).type ?? "")
              .trim()
              .toLowerCase();
            return ![
              "task_trace",
              "security_decision",
              "reasoning_trace",
              "tool_trace",
            ].includes(type);
          });
        }
        const nestedKeys =
          normalizePublicInferenceKey(key) === "metadata"
            ? NORMALIZED_INTERNAL_INFERENCE_KEYS
            : internalKeys;
        return [
          key,
          sanitizeBoundedPublicJson(nestedValue, nestedKeys, depth + 1),
        ];
      }),
  );
}

export function sanitizePublicInferenceValue(
  value: unknown,
  depth = 0,
): unknown {
  return sanitizeBoundedPublicJson(
    value,
    NORMALIZED_INTERNAL_INFERENCE_KEYS,
    depth,
  );
}

export function sanitizePublicTaskEventPayload(
  value: unknown,
  depth = 0,
): unknown {
  return sanitizeBoundedPublicJson(
    value,
    NORMALIZED_INTERNAL_EVENT_PAYLOAD_KEYS,
    depth,
  );
}

function extractTaskOperatorSummary(value: unknown) {
  const result = readRecord(value);
  const operator = readRecord(result?.operator);
  if (!operator) {
    return null;
  }
  return {
    runId: readString(operator, "runId"),
    status: readString(operator, "status"),
    currentStep: readNumber(operator, "currentStep"),
    requiresApproval: readBoolean(operator, "requiresApproval"),
    activeApp: readString(operator, "activeApp"),
    activeWindow: readString(operator, "activeWindow"),
    lastVerificationOk: readBoolean(operator, "lastVerificationOk"),
    observationId: readString(operator, "observationId"),
    stopReason: readString(operator, "stopReason"),
  };
}

function readRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function readString(
  record: Record<string, unknown> | null,
  key: string,
): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function readPublicSkillId(
  record: Record<string, unknown> | null,
): string | null {
  const value = readString(record, "skillId");
  return value && /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$/.test(value)
    ? value
    : null;
}

function readBoolean(
  record: Record<string, unknown> | null,
  key: string,
): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function readStringList(
  record: Record<string, unknown> | null,
  key: string,
): string[] {
  const value = record?.[key];
  return Array.isArray(value)
    ? value.map((item) => String(item ?? "").trim()).filter(Boolean)
    : [];
}

function readNumber(
  record: Record<string, unknown> | null,
  key: string,
): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function hasQuantumCapability(task: MobileTaskFeedRow): boolean {
  const requested = Array.isArray(task.requestedCapabilities)
    ? task.requestedCapabilities
    : [];
  return requested.some((capability) =>
    String(capability ?? "")
      .trim()
      .toLowerCase()
      .replace(/[\s_]+/g, ".")
      .startsWith("quantum."),
  );
}

function normalizeTaskQuantumSnapshot(value: unknown) {
  const record = readRecord(value);
  if (!record) {
    return null;
  }
  const mode = readString(record, "mode") ?? "hybrid";
  return {
    mode,
    ready: readBoolean(record, "ready") ?? undefined,
    supportedProblemClasses: readStringList(record, "supportedProblemClasses"),
    solver: readString(record, "solver") ?? undefined,
    problemClass: readString(record, "problemClass") ?? undefined,
    benchmarkStatus: readString(record, "benchmarkStatus") ?? undefined,
    fallbackReason: readString(record, "fallbackReason") ?? undefined,
    lastBenchmarkScore: readNumber(record, "lastBenchmarkScore") ?? undefined,
  };
}

function normalizeTaskQuantumLivenessSnapshot(value: unknown) {
  const record = readRecord(value);
  if (
    !record ||
    readString(record, "strategy") !== "quantum_runtime_liveness_snapshot_v1" ||
    readString(record, "source") !== "desktop_runtime_progress"
  ) {
    return null;
  }
  const timeoutRisk = readString(record, "livenessGuardTimeoutRisk");
  return {
    strategy: "quantum_runtime_liveness_snapshot_v1",
    source: "desktop_runtime_progress",
    score: readNumber(record, "score"),
    qualified: readBoolean(record, "qualified") ?? false,
    backendResponsiveActive:
      readBoolean(record, "backendResponsiveActive") ?? false,
    responsiveBoostedStepCount:
      readNumber(record, "responsiveBoostedStepCount") ?? 0,
    responsiveBoostedStepIds: readStringList(
      record,
      "responsiveBoostedStepIds",
    ).slice(0, 16),
    livenessGuardActive: readBoolean(record, "livenessGuardActive") ?? false,
    livenessGuardTimeoutRisk:
      timeoutRisk === "low" ||
      timeoutRisk === "medium" ||
      timeoutRisk === "high"
        ? timeoutRisk
        : null,
    livenessGuardEffectiveMaxReplans:
      readNumber(record, "livenessGuardEffectiveMaxReplans") ?? null,
    repairAttemptCount: readNumber(record, "repairAttemptCount") ?? 0,
  };
}

function extractTaskQuantumSnapshot(task: MobileTaskFeedRow) {
  const payload = readRecord(task.payload);
  const metadata = readRecord(payload?.metadata);
  const result = readRecord(task.result);
  const resultTrace = readRecord(result?.executionTrace);
  const payloadTrace = readRecord(payload?.executionTrace);
  const metadataTrace = readRecord(metadata?.executionTrace);
  const runtimeLiveness =
    normalizeTaskQuantumLivenessSnapshot(resultTrace?.quantumLiveness) ??
    normalizeTaskQuantumLivenessSnapshot(payloadTrace?.quantumLiveness) ??
    normalizeTaskQuantumLivenessSnapshot(metadataTrace?.quantumLiveness);
  const candidate =
    normalizeTaskQuantumSnapshot(result?.quantum) ??
    normalizeTaskQuantumSnapshot(payload?.quantum) ??
    normalizeTaskQuantumSnapshot(metadata?.quantum);
  if (candidate) {
    return runtimeLiveness ? { ...candidate, runtimeLiveness } : candidate;
  }
  if (!hasQuantumCapability(task)) {
    return runtimeLiveness ? { mode: "hybrid", runtimeLiveness } : null;
  }
  const fallback = {
    mode: "hybrid",
    ready: task.status !== "failed",
    supportedProblemClasses: ["qubo", "ising", "qaoa", "vqe"],
    solver: "qiskit_simulator",
    problemClass: "optimization",
    benchmarkStatus:
      task.status === "completed"
        ? "completed"
        : task.status === "failed"
          ? "failed"
          : "pending",
    fallbackReason: task.error ?? undefined,
    lastBenchmarkScore: undefined,
  };
  return runtimeLiveness ? { ...fallback, runtimeLiveness } : fallback;
}

export function extractTaskChatSessionId(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }

  const metadata = (payload as Record<string, unknown>).metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return null;
  }

  const chat = (metadata as Record<string, unknown>).chat;
  if (!chat || typeof chat !== "object" || Array.isArray(chat)) {
    return null;
  }

  const sessionId = (chat as Record<string, unknown>).sessionId;
  return typeof sessionId === "string" && sessionId.trim().length > 0
    ? sessionId.trim()
    : null;
}

export function extractTaskSupersedesTaskId(payload: unknown): string | null {
  const metadata = readRecord(readRecord(payload)?.metadata);
  const intervention = readRecord(metadata?.intervention);
  if (readString(intervention, "kind") !== "redirect_after_cancel") {
    return null;
  }
  const taskId = readString(intervention, "supersedesTaskId");
  return taskId &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(
      taskId,
    )
    ? taskId
    : null;
}

export function extractTaskPresentation(payload: unknown): "chat" | "task" {
  const metadata = readRecord(readRecord(payload)?.metadata);
  const explicit = readString(metadata, "presentation");
  if (explicit === "chat" || explicit === "task") {
    return explicit;
  }

  const routeDecision =
    readRecord(metadata?.routeDecision) ??
    readRecord(metadata?.routingDecision);
  const route = readString(routeDecision, "route");
  return route === "server_brain" ? "chat" : "task";
}

export function extractTaskRouteDecision(payload: unknown) {
  const metadata = readRecord(readRecord(payload)?.metadata);
  const routeDecision =
    readRecord(metadata?.routeDecision) ??
    readRecord(metadata?.routingDecision);
  if (!routeDecision) {
    return null;
  }
  const taskRoute = readRecord(routeDecision.taskRoute);

  return {
    route: readString(routeDecision, "route"),
    taskRoute: taskRoute
      ? {
          target: readString(taskRoute, "target"),
          operationalRoute: readString(taskRoute, "operationalRoute"),
          executionPlan: readStringList(taskRoute, "executionPlan"),
          reason: readString(taskRoute, "reason"),
          needsDesktop: readBoolean(taskRoute, "needsDesktop"),
          needsPrivateDesktopData: readBoolean(
            taskRoute,
            "needsPrivateDesktopData",
          ),
          needsUserApproval: readBoolean(taskRoute, "needsUserApproval"),
          requiredCapabilities: readStringList(
            taskRoute,
            "requiredCapabilities",
          ),
        }
      : null,
    mode: readString(routeDecision, "mode"),
    intent: readString(routeDecision, "intent"),
    confidence: readNumber(routeDecision, "confidence"),
    privacyClass: readString(routeDecision, "privacyClass"),
    privacyLevel: readString(routeDecision, "privacyLevel"),
    requiresApproval: readBoolean(routeDecision, "requiresApproval"),
    requiredRuntime: readString(routeDecision, "requiredRuntime"),
    shouldAskClarification: readBoolean(
      routeDecision,
      "shouldAskClarification",
    ),
    failClosedReason: readString(routeDecision, "failClosedReason"),
    selectedWorkload: readString(routeDecision, "selectedWorkload"),
    reason: readString(routeDecision, "reason"),
    userFacingMessage: readString(routeDecision, "userFacingMessage"),
    capabilities: readStringList(routeDecision, "capabilities"),
  };
}

export function deriveTaskDeliveryState(
  task: Pick<
    MobileTaskFeedRow,
    | "status"
    | "runtimeConnectionId"
    | "dispatchLeaseId"
    | "dispatchLeaseExpiresAt"
    | "dispatchAckAt"
  >,
): TaskDeliveryState {
  if (task.dispatchLeaseId && task.dispatchLeaseExpiresAt) {
    return "dispatched";
  }
  if (
    task.dispatchAckAt ||
    task.status === "running" ||
    task.status === "waiting_approval"
  ) {
    return "acked";
  }
  if (task.runtimeConnectionId) {
    return "recovering";
  }
  return "queued";
}

export function getPayloadMetadata(
  payload: Record<string, unknown>,
): Record<string, unknown> {
  const metadata = payload.metadata;
  return normalizeLocalDerivedMetadata(
    metadata && typeof metadata === "object" && !Array.isArray(metadata)
      ? { ...metadata }
      : {},
  );
}

export function getTaskPrompt(payload: Record<string, unknown>): string {
  return typeof payload.prompt === "string" ? payload.prompt : "";
}

export function extractSharedBrainConversation(
  payload: Record<string, unknown>,
): SharedBrainConversationMessage[] | undefined {
  const brainContext = payload.brainContext;
  if (
    !brainContext ||
    typeof brainContext !== "object" ||
    Array.isArray(brainContext)
  ) {
    return undefined;
  }

  const conversation = (brainContext as Record<string, unknown>).conversation;
  if (!Array.isArray(conversation)) {
    return undefined;
  }

  return conversation
    .map((item) => {
      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return null;
      }

      const record = item as Record<string, unknown>;
      const role = record.role;
      const content = record.content;

      if (
        (role !== "system" && role !== "user" && role !== "assistant") ||
        typeof content !== "string" ||
        !content.trim()
      ) {
        return null;
      }

      return {
        role: role as SharedBrainConversationMessage["role"],
        content,
      };
    })
    .filter((item): item is SharedBrainConversationMessage => item != null);
}

export function getSharedBrainFallbackMessage(
  error: unknown,
  fallback = "Yanıt katmanı bu tur tamamlayamadı. İsteğini aldım; güvenli olduğunda kısa, eldeki bağlamla devam ediyorum.",
) {
  if (error instanceof Error && error.message.trim()) {
    const message = error.message.trim();
    return looksLikeUnsafeBackendError(message) ? fallback : message;
  }

  return fallback;
}

const CONTINUITY_CHAT_WORKLOADS = new Set([
  "fast_route",
  "mobile_chat_balanced",
  "mobile_chat_fast",
  // CANLI ARIZA (2026-07-30): "Nazım Hikmet kimdir? 250 kelimelik belge
  // gövdesi yaz" isteği `document_generate` yüküyle geldi, sağlayıcı zinciri
  // tükendi ve bu küme onu tanımadığı için kullanıcı ham yedek sentinel
  // metnini gördü. Düz metin üretimi de sohbet kadar kamusaldır.
  "document_generate",
]);

/**
 * Süreklilik cevabı üretilebilecek niyetler. Hepsi ÜRETİM niyetidir: yan
 * etkisi, özel verisi ve araç bağımlılığı yoktur — aşağıdaki kapılar bunu
 * ayrıca doğrular. Araç/onay/özel veri gerektiren her şey fail-closed kalır.
 */
const CONTINUITY_CHAT_INTENTS = new Set([
  "normal_chat",
  "writing",
  "research",
]);

/**
 * Produces a zero-model-call continuation only for ordinary public chat.
 * Tool calls, private/attachment context, approvals and policy denials stay
 * fail-closed so availability never weakens Elyan's safety boundary.
 */
export function resolveSafeChatContinuityReply(input: {
  prompt: string;
  channel: unknown;
  route: unknown;
  mode: unknown;
  privacyClass: unknown;
  requiresApproval: unknown;
  intent: unknown;
  requiredRuntime: unknown;
  shouldAskClarification: unknown;
  failClosedReason: unknown;
  workload: unknown;
  taskRoute: unknown;
  routeCapabilities: unknown;
  requestedCapabilities: unknown;
  metadata: Record<string, unknown>;
  understandingEnvelope: unknown;
  errorCode: string;
  failureClass: unknown;
}): string | null {
  if (
    input.channel !== "chat" ||
    input.route !== "server_brain" ||
    input.mode !== "chat" ||
    input.privacyClass !== "public_text" ||
    input.requiresApproval === true ||
    !CONTINUITY_CHAT_INTENTS.has(String(input.intent ?? "")) ||
    input.requiredRuntime !== "server" ||
    input.shouldAskClarification !== false ||
    input.failClosedReason != null ||
    !CONTINUITY_CHAT_WORKLOADS.has(String(input.workload ?? "")) ||
    !["server_brain_unavailable", "chat_queue_unavailable"].includes(
      input.errorCode,
    ) ||
    input.failureClass === "policy_blocked"
  ) {
    return null;
  }

  const routeCapabilities = Array.isArray(input.routeCapabilities)
    ? input.routeCapabilities.filter(Boolean)
    : [];
  const requestedCapabilities = Array.isArray(input.requestedCapabilities)
    ? input.requestedCapabilities.filter(Boolean)
    : [];
  if (routeCapabilities.length > 0 || requestedCapabilities.length > 0) {
    return null;
  }

  const taskRoute =
    input.taskRoute &&
    typeof input.taskRoute === "object" &&
    !Array.isArray(input.taskRoute)
      ? (input.taskRoute as Record<string, unknown>)
      : null;
  if (
    taskRoute?.needsPrivateDesktopData === true ||
    taskRoute?.needsUserApproval === true ||
    (Array.isArray(taskRoute?.requiredCapabilities) &&
      taskRoute.requiredCapabilities.length > 0)
  ) {
    return null;
  }

  const envelope =
    input.understandingEnvelope &&
    typeof input.understandingEnvelope === "object" &&
    !Array.isArray(input.understandingEnvelope)
      ? (input.understandingEnvelope as Record<string, unknown>)
      : null;
  const risk =
    envelope?.risk &&
    typeof envelope.risk === "object" &&
    !Array.isArray(envelope.risk)
      ? (envelope.risk as Record<string, unknown>)
      : null;
  if (
    risk?.local_private === true ||
    risk?.side_effect === true ||
    (Array.isArray(envelope?.required_capabilities) &&
      envelope.required_capabilities.some((capability) => {
        if (
          !capability ||
          typeof capability !== "object" ||
          Array.isArray(capability)
        ) {
          return true;
        }
        return (capability as Record<string, unknown>).name !== "chat.reply";
      }))
  ) {
    return null;
  }

  if (
    (Array.isArray(input.metadata.attachments) &&
      input.metadata.attachments.length > 0) ||
    (Array.isArray(input.metadata.clientAttachments) &&
      input.metadata.clientAttachments.length > 0) ||
    (Array.isArray(input.metadata.client_attachments) &&
      input.metadata.client_attachments.length > 0) ||
    (Array.isArray(input.metadata.mediaInputRefs) &&
      input.metadata.mediaInputRefs.length > 0) ||
    input.metadata.remoteMcpSelection != null ||
    input.metadata.connectorWriteApproval != null ||
    input.metadata.freshData != null ||
    input.metadata.webGrounding != null
  ) {
    return null;
  }

  const prompt = input.prompt.replace(/\s+/g, " ").trim();
  if (!prompt) return null;
  // NOT: Burada "teorem" geçen her prompta Pisagor teoremini döndüren sabit bir
  // dal vardı. Bayes, Fermat, Gödel — hepsine aynı yanlış cevap gidiyordu.
  // Süreklilik katmanı bir BİLGİ kaynağı değildir; bilmediğini uydurmak yerine
  // dürüstçe "bu tur tamamlanamadı" demelidir.
  const asksQuestion =
    /[?？]\s*$/u.test(prompt) ||
    /^(?:kim|ne|neden|niçin|nicin|nasıl|nasil|nerede|nereye|hangi|kaç|kac|what|why|how|where|which|who)\b/iu.test(
      prompt,
    );
  return asksQuestion
    ? "Kısa cevap vereyim: Bu tur model yanıtı tamamlanamadı, ama isteğin düz sohbet kapsamında. Daha net bir cevap için işlemi arka planda yeniden deniyorum."
    : "İsteğini aldım. Yanıt katmanı bu tur tamamlanamadı; güvenli olduğunda kısa cevapla devam ediyorum.";
}

function looksLikeUnsafeBackendError(message: string) {
  const lowered = message.toLowerCase();
  const rawTransportFailure =
    lowered.includes("fetch failed") ||
    lowered.includes("failed to fetch") ||
    lowered.includes("connection refused") ||
    lowered.includes("network error") ||
    lowered.includes("socket hang up") ||
    lowered.includes("timed out") ||
    lowered.includes("timeout");
  if (rawTransportFailure) {
    return true;
  }

  const hasEndpoint =
    lowered.includes("http://") ||
    lowered.includes("https://") ||
    lowered.includes("localhost") ||
    lowered.includes("127.0.0.1") ||
    /\b\d{1,3}(?:\.\d{1,3}){3}\b/.test(lowered);

  if (!hasEndpoint) {
    return false;
  }

  return (
    lowered.includes("error") ||
    lowered.includes("failed") ||
    lowered.includes("provider") ||
    lowered.includes("endpoint") ||
    lowered.includes("host") ||
    lowered.includes("socket") ||
    lowered.includes("connection")
  );
}

export function createTaskFingerprint(input: {
  targetDeviceId: string;
  title: string;
  payload: Record<string, unknown>;
  requestedCapabilities: string[];
}) {
  return createIdempotencyFingerprint({
    targetDeviceId: input.targetDeviceId,
    title: input.title,
    payload: input.payload,
    requestedCapabilities: input.requestedCapabilities,
  });
}

export function resolveIdempotentTaskMatch<T extends IdempotentTaskRow>(
  existingTask: T | null,
  input: {
    idempotencyKey?: string;
    fingerprint?: string;
  },
) {
  if (!input.idempotencyKey || !input.fingerprint || !existingTask) {
    return null;
  }

  if (existingTask.idempotencyFingerprint !== input.fingerprint) {
    throw new AppError(
      409,
      "idempotency_conflict",
      "Idempotency key is already bound to a different task payload",
      {
        idempotencyKey: input.idempotencyKey,
        existingTaskId: existingTask.id,
      },
    );
  }

  return existingTask;
}

export function assertOwnedDesktopTaskTarget(
  device: OwnedDesktopTaskTarget,
  targetDeviceId: string,
): void {
  if (!device.isActive) {
    throw new AppError(
      409,
      "device_inactive",
      "Target desktop runtime is inactive",
      {
        targetDeviceId,
        canReceiveTasks: device.canReceiveTasks,
        isOnline: device.isOnline,
        targetStatus: device.targetStatus,
      },
    );
  }

  if (device.targetStatus === "backend_unreachable") {
    throw new AppError(
      409,
      "runtime_unreachable",
      "Backend APP_BASE_URL is not reachable by external clients, so desktop tasks cannot be accepted safely",
      {
        targetDeviceId,
        canReceiveTasks: device.canReceiveTasks,
        isOnline: device.isOnline,
        targetStatus: device.targetStatus,
      },
    );
  }

  if (device.targetStatus === "plan_restricted") {
    throw new AppError(
      409,
      "desktop_plan_required",
      "Desktop connection is available on Solo and Pro plans",
      {
        targetDeviceId,
        canReceiveTasks: device.canReceiveTasks,
        isOnline: device.isOnline,
        targetStatus: device.targetStatus,
      },
    );
  }

  if (device.targetStatus === "runtime_stale") {
    throw new AppError(
      409,
      "runtime_unavailable",
      "Target desktop runtime heartbeat is stale",
      {
        targetDeviceId,
        canReceiveTasks: device.canReceiveTasks,
        isOnline: device.isOnline,
        targetStatus: device.targetStatus,
        lastHeartbeatAt: device.runtime.lastHeartbeatAt,
      },
    );
  }

  if (!device.isOnline || !device.canReceiveTasks) {
    throw new AppError(
      409,
      "device_offline",
      "Target desktop runtime is offline or has not registered",
      {
        targetDeviceId,
        canReceiveTasks: device.canReceiveTasks,
        isOnline: device.isOnline,
        targetStatus: device.targetStatus,
        lastHeartbeatAt: device.runtime.lastHeartbeatAt,
      },
    );
  }
}

export function createInvalidTargetDeviceError(
  targetDeviceId: string,
): AppError {
  return unprocessableEntity("Target device is not a valid desktop runtime", {
    targetDeviceId,
    expectedTarget:
      "Use the desktop device `id` returned by /v1/mobile/bootstrap.devices",
    expectedDeviceType: "desktop",
    error: "invalid_target",
  });
}

export function createRuntimeCapabilityMismatchError(input: {
  targetDeviceId: string;
  requestedCapabilities: string[];
  availableCapabilities: string[];
  missingCapabilities: string[];
}): AppError {
  return new AppError(
    409,
    "runtime_capability_mismatch",
    "Target desktop runtime does not support the requested capability set",
    {
      targetDeviceId: input.targetDeviceId,
      requestedCapabilities: input.requestedCapabilities,
      availableCapabilities: input.availableCapabilities,
      missingCapabilities: input.missingCapabilities,
    },
  );
}

export function createStaleRuntimeConnectionError(): AppError {
  return new AppError(
    401,
    "unauthorized",
    "Runtime connection is stale or has been replaced",
  );
}

export function createTaskRuntimeOwnershipConflictError(input: {
  taskId: string;
  activeConnectionId: string;
  owningConnectionId: string;
}): AppError {
  return new AppError(
    409,
    "task_runtime_owner_conflict",
    "Task is owned by another active runtime connection",
    {
      taskId: input.taskId,
      activeConnectionId: input.activeConnectionId,
      owningConnectionId: input.owningConnectionId,
    },
  );
}
