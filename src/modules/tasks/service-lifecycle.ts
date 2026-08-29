import type { TaskStatus } from "../../contracts/domain.js";
import { tasks } from "../../db/schema.js";
import {
  shouldAutomaticallyApproveUserTool,
  type ApprovalToolIdempotency,
  type ApprovalToolPermission,
  type UserApprovalMode,
} from "../approval-policy/policy.js";
import {
  buildInteractionEnvelope,
  interactionActionsForKind,
  interactionEnvelopeSchema,
  normalizeInteractionKind,
  type InteractionAction,
  type InteractionEnvelope,
  type InteractionKind,
} from "../../contracts/interaction.js";
import { asRecord as readRecord } from "../../lib/record.js";

export function buildTaskRuntimeOwnershipUpdate(input: { runtimeConnectionId: string; now?: Date }) {
  return {
    runtimeConnectionId: input.runtimeConnectionId,
    updatedAt: input.now ?? new Date(),
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export const TASK_DISPATCH_LEASE_MS = 45_000;
export const CHAT_TASK_DEADLINE_MS = 4 * 60_000;
export const DESKTOP_TASK_DEADLINE_MS = 30 * 60_000;
export const LONG_TASK_DEADLINE_MS = 2 * 60 * 60_000;

export type TaskExecutionClass = "chat" | "desktop" | "long";

export function taskExecutionDeadline(input: {
  executionClass: TaskExecutionClass;
  now?: Date;
}) {
  const now = input.now ?? new Date();
  const duration = input.executionClass === "chat"
    ? CHAT_TASK_DEADLINE_MS
    : input.executionClass === "long"
      ? LONG_TASK_DEADLINE_MS
      : DESKTOP_TASK_DEADLINE_MS;
  return new Date(now.getTime() + duration);
}
/**
 * Onay bekleyen bir görevin yaşam süresi.
 *
 * 10 dakikaydı; 1 dakikaya indirildi. Gerekçe: onay bir SORUDUR ve sorunun
 * bağlamı hızla bayatlar — kullanıcı "şu klasörü sil" dedikten iki dakika
 * sonra artık başka bir işin içindedir, gelen onay kutusu ise hangi isteğe
 * ait olduğu unutulmuş bir kalıntıdır. Süresi dolan görev `approval_expired`
 * ile kapanır; kullanıcı isterse isteği tekrarlar, bu ucuzdur.
 *
 * Bunu uygulayan süpürücü `lease-sweeper.ts` içindedir ve 30 saniyede bir
 * koşar: pratikte bir onay en geç ~1,5 dakikada kapanır.
 */
export const TASK_APPROVAL_TTL_MS = 60_000;

/**
 * Masaüstüne hiç teslim edilemeden kuyrukta bekleyen görevin yaşam süresi.
 *
 * Canlı bulgu (2026-07-30): kuyrukta 13 görev asılıydı, en eskisi ÜÇ HAFTA
 * öncesinden ("Safari aç"). Süpürücü `queued` durumunu hiç taramıyordu, bu
 * yüzden masaüstü o an kapalıysa görev sonsuza kadar kalıyordu. İki zararı
 * vardı: görev listesini kirletiyordu ve masaüstü sonunda bağlandığında
 * haftalar öncesinden bir komutun çalışma ihtimali doğuyordu.
 *
 * 10 dakika: masaüstünün kısa bir kopması görevi öldürmez, ama kuyruk da
 * arşive dönüşmez.
 */
export const TASK_QUEUE_TTL_MS = 10 * 60_000;

/**
 * Bitmiş görevlerin saklama süresi — sonunda KALICI olarak silinirler.
 *
 * Elyan'ın son işleri hatırlaması için bir haftalık pencere yeterlidir:
 * "dün oluşturduğun raporu aç" çalışır, üç hafta önceki bir kayıt ise
 * hatırlamaya değer bir bağlam değil, sadece taşınan yüktür.
 *
 * `canceled` olarak bırakmak yetmiyor: satır tabloda durdukça sorgular,
 * indeksler ve görev listeleri onu taşımaya devam eder. Süre dolunca kayıt
 * gerçekten silinir; bağımlı satırlar şemadaki `cascade`/`set null`
 * kurallarıyla birlikte temizlenir.
 *
 * Yalnız TERMİNAL durumdakiler silinir — çalışan ya da onay bekleyen bir
 * görev yaşına bakılmaksızın korunur.
 */
export const TASK_RETENTION_MS = 7 * 24 * 60 * 60_000;
export const MAX_ACTIVE_USER_APPROVALS = 8;
export const MAX_TASK_DISPATCH_ATTEMPTS = 5;

function readString(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

export function approvalRequestRevision(approvalRequest: unknown): number {
  const request = readRecord(approvalRequest);
  const interaction = readRecord(request?.interaction);
  return Math.max(
    1,
    Math.floor(readNumber(request?.revision) ?? readNumber(interaction?.revision) ?? 1),
  );
}

export function approvalRequestKey(approvalRequest: unknown): string {
  const request = readRecord(approvalRequest);
  return readString(request?.approvalKey) || readString(request?.token);
}

/**
 * Public approval event fields shared by every approval resolution path.
 *
 * Approval tokens and free-form notes are intentionally excluded: clients
 * need a stable request identity and resolution state, never a credential or
 * private execution detail.
 */
export function buildPublicTaskApprovalEventFields(
  approvalRequest: unknown,
  input: { status?: string; updatedAt?: Date } = {},
) {
  const request = readRecord(approvalRequest);
  const interactionResult = interactionEnvelopeSchema.safeParse(request?.interaction);
  const interaction = interactionResult.success ? interactionResult.data : null;
  const resolution =
    readRecord(request?.resolution) ??
    readRecord(readRecord(request?.interaction)?.resolution);
  const approved = typeof resolution?.approved === "boolean"
    ? resolution.approved
    : null;
  const resolutionRevision = readNumber(resolution?.revision);
  // Kanonik `state`/`action` varsa o kazanır: netleştirme yanıtı bir onay
  // değildir ve boolean bu farkı taşıyamaz.
  const resolutionState = readString(resolution?.state)
    || (readString(resolution?.action) === "answer" ? "answered" : "")
    || (approved === true
      ? "approved"
      : approved === false
        ? "rejected"
        : "")
    || null;

  return {
    ...(interaction
      ? {
          interaction,
          interactionKind: interaction.kind,
          interactionId: interaction.id,
          interactionRevision: interaction.revision,
        }
      : {}),
    approvalKey: readString(request?.approvalKey) || null,
    approvalRevision: approvalRequestRevision(request),
    status: readString(input.status) || null,
    resolution: resolution
      ? {
          approved,
          state: resolutionState,
          resolvedAt: readString(resolution.resolvedAt) || null,
          revision: resolutionRevision == null
            ? approvalRequestRevision(request)
            : Math.max(1, Math.floor(resolutionRevision)),
        }
      : null,
    updatedAt: (input.updatedAt ?? new Date()).toISOString(),
  };
}

export function approvalRequestExpiresAt(
  approvalRequest: unknown,
  now: Date = new Date(),
): string {
  const request = readRecord(approvalRequest);
  const interaction = readRecord(request?.interaction);
  const existing =
    readString(interaction?.expiresAt) || readString(request?.expiresAt);
  if (existing) return existing;
  return new Date(now.getTime() + TASK_APPROVAL_TTL_MS).toISOString();
}

export function isApprovalRequestExpired(
  approvalRequest: unknown,
  now: Date = new Date(),
): boolean {
  const request = readRecord(approvalRequest);
  const interaction = readRecord(request?.interaction);
  const expiresAt =
    readString(interaction?.expiresAt) || readString(request?.expiresAt);
  if (!expiresAt) return false;
  const parsed = Date.parse(expiresAt);
  return Number.isFinite(parsed) && parsed <= now.getTime();
}

export function isApprovalAlreadyResolved(approvalRequest: unknown): boolean {
  const request = readRecord(approvalRequest);
  const resolution =
    readRecord(request?.resolution) ??
    readRecord(readRecord(request?.interaction)?.resolution);
  return resolution?.approved === true || resolution?.approved === false;
}

export function normalizeTaskApprovalRequest(
  approvalRequest: unknown,
  input: {
    taskId: string;
    now?: Date;
  },
): Record<string, unknown> & {
  kind: string;
  source: string;
  approvalKey: string;
  revision: number;
  expiresAt: string;
  surface: string;
  permissionSurface?: string;
  permissionSummary?: string;
  interaction: InteractionEnvelope;
  availableActions: string[];
} {
  const now = input.now ?? new Date();
  const request = readRecord(approvalRequest) ?? {};
  const revision = approvalRequestRevision(request);
  const existingKey = approvalRequestKey(request);
  const taskKey = (readString(input.taskId) || "task").slice(0, 255);
  const kind = readString(request.kind) || "permission";
  const interaction = readRecord(request.interaction) ?? {};
  const interactionKind: InteractionKind = normalizeInteractionKind(
    readString(interaction.kind) || kind,
  );
  const {
    surface: _surface,
    permissionSurface: _permissionSurface,
    permissionSummary: _permissionSummary,
    availableActions: _availableActions,
    ...baseRequest
  } = request;
  const rawExpiresAt = approvalRequestExpiresAt(request, now);
  const parsedExpiresAt = Date.parse(rawExpiresAt);
  const expiresAt = Number.isFinite(parsedExpiresAt) && parsedExpiresAt > now.getTime()
    ? new Date(parsedExpiresAt).toISOString()
    : new Date(now.getTime() + TASK_APPROVAL_TTL_MS).toISOString();
  const common = {
    ...baseRequest,
    kind,
    source: readString(request.source) || "desktop_runtime",
    approvalKey: existingKey || `${taskKey}:${revision}`,
    revision,
    expiresAt,
  };
  const interactionId =
    readString(interaction.id) ||
    readString(request.interactionId) ||
    readString(request.id) ||
    `${taskKey}:interaction:${revision}`;
  const taskRunId =
    readString(interaction.taskRunId) ||
    readString(request.taskRunId) ||
    readString(request.runId) ||
    taskKey;
  const question =
    readString(interaction.question) ||
    readString(request.question) ||
    readString(request.message);
  const summary =
    readString(interaction.summary) ||
    readString(request.summary) ||
    readString(request.permissionSummary);
  const boundedInteractionId = interactionId.slice(0, 255);
  const boundedTaskRunId = taskRunId.slice(0, 255);
  const boundedQuestion = question.slice(0, 1_000);
  const boundedSummary = summary.slice(0, 1_000);
  const interactionResolution =
    readRecord(request.resolution) ?? readRecord(interaction.resolution);
  const availableActions = interactionActionsForKind(interactionKind);
  const canonicalInteraction = buildInteractionEnvelope({
    id: boundedInteractionId,
    taskId: taskKey,
    taskRunId: boundedTaskRunId,
    kind: interactionKind,
    revision,
    question: boundedQuestion,
    summary: boundedSummary,
    expiresAt,
    resolution: interactionResolution,
  });
  if (interactionKind === "clarification") {
    return {
      ...common,
      expiresAt,
      surface: "clarification",
      interaction: canonicalInteraction,
      availableActions: [...availableActions],
    };
  }
  return {
    ...common,
    expiresAt,
    surface: "full_computer_access",
    permissionSurface: "full_computer_access",
    interaction: canonicalInteraction,
    availableActions: [...availableActions],
    permissionSummary:
      readString(request.permissionSummary) ||
      "Elyan bu görevi tamamlamak için bilgisayar erişimini tek onay altında kullanacak.",
  };
}

/**
 * Normalize an approval payload at every public read boundary as well as on
 * writes. Empty approval fields stay empty; an actual interaction gets the
 * same canonical envelope in REST, history, bootstrap and SSE consumers.
 */
export function normalizePublicTaskApprovalRequest(
  approvalRequest: unknown,
  taskId: string,
): unknown {
  const request = readRecord(approvalRequest);
  if (!request || Object.keys(request).length === 0) {
    return approvalRequest ?? null;
  }
  return normalizeTaskApprovalRequest(request, { taskId });
}

/**
 * Bir görevin bekleyen etkileşimi — TEK kanonik zarf.
 *
 * REST, SSE, history ve bootstrap aynı değeri okur. İstemci kart tipini
 * `status === "waiting_approval"` üzerinden çıkarmaz; bu zarfın `kind`,
 * `availableActions`, `id`, `revision` ve `expiresAt` alanlarını kullanır.
 * Çözülmüş ya da süresi dolmuş bir etkileşim artık beklemede değildir.
 */
export function extractPublicInteraction(
  approvalRequest: unknown,
  taskId: string,
  now: Date = new Date(),
): (InteractionEnvelope & { state: "pending" | "resolved" | "expired" }) | null {
  const request = readRecord(approvalRequest);
  if (!request || Object.keys(request).length === 0) {
    return null;
  }
  const normalized = normalizeTaskApprovalRequest(request, { taskId, now });
  const state = isApprovalAlreadyResolved(request)
    ? "resolved"
    : isApprovalRequestExpired(normalized, now)
      ? "expired"
      : "pending";
  return { ...normalized.interaction, state };
}

const trustedDesktopIdempotentWriteCapabilities = new Set([
  "clipboard_write",
  "document_write",
  "spreadsheet_write",
  "presentation_write",
  "canvas_write",
]);

const trustedDesktopReadOnlyCapabilities = new Set([
  "clipboard_read",
  "data_analyze",
  "desktop_os.permissions",
  "desktop_os.status",
  "directory_tree",
  "document_read",
  "email_draft",
  "file_read",
  "file_search",
  "get_calendar_events",
  "get_reminders",
  "get_weather",
  "get_youtube_channel_report",
  "git_diff",
  "git_status",
  "image_read",
  "latex_parse",
  "math_solve",
  "ocr_read",
  "quantum_compare_classical",
  "quantum_generate_report",
  "quantum_model_problem",
  "quantum_run_experiment",
  "retrieve_context",
  "speech_to_text",
  "sys_info",
  "text_analyze",
  "web_research",
]);

function hasOnlyTrustedDesktopApprovalSteps(approvalRequest: Record<string, unknown>) {
  if (!Array.isArray(approvalRequest.steps) || approvalRequest.steps.length === 0) {
    return false;
  }
  let hasIdempotentWrite = false;
  for (const value of approvalRequest.steps) {
    const step = readRecord(value);
    const capability = typeof step?.capability === "string"
      ? step.capability.trim()
      : "";
    if (step?.overwrite === true) {
      return false;
    }
    if (trustedDesktopIdempotentWriteCapabilities.has(capability)) {
      hasIdempotentWrite = true;
      continue;
    }
    if (!trustedDesktopReadOnlyCapabilities.has(capability)) {
      return false;
    }
  }
  return hasIdempotentWrite;
}

export function shouldAutoApproveDesktopTask(input: {
  status: TaskStatus;
  payload: unknown;
  approvalMode: UserApprovalMode;
  approvalRequest: unknown;
}) {
  if (input.status !== "waiting_approval") return false;

  const payload = readRecord(input.payload);
  const metadata = readRecord(payload?.metadata);
  const routeDecision = readRecord(metadata?.routeDecision);
  const taskRoute = readRecord(routeDecision?.taskRoute);
  const approvalRequest = readRecord(input.approvalRequest);
  const permission = approvalRequest?.permission;
  const idempotency = approvalRequest?.idempotency;
  const capability = typeof approvalRequest?.capability === "string"
    ? approvalRequest.capability.trim()
    : "";
  const safelyClassified = shouldAutomaticallyApproveUserTool({
    mode: input.approvalMode,
    permission:
      permission === "read" || permission === "write" || permission === "side_effect"
        ? (permission as ApprovalToolPermission)
        : undefined,
    idempotency:
      idempotency === "read_only" ||
      idempotency === "idempotent_write" ||
      idempotency === "non_idempotent"
        ? (idempotency as ApprovalToolIdempotency)
        : undefined,
  });

  return metadata?.desktopDispatch === true
    && approvalRequest?.source === "desktop_runtime"
    && input.approvalMode === "trusted_idempotent_writes"
    && permission === "write"
    && idempotency === "idempotent_write"
    && trustedDesktopIdempotentWriteCapabilities.has(capability)
    && approvalRequest.manualApprovalRequired !== true
    && hasOnlyTrustedDesktopApprovalSteps(approvalRequest)
    && safelyClassified
    && (routeDecision?.route === "desktop_runtime"
      || taskRoute?.operationalRoute === "desktop_runtime");
}

export function buildTaskDispatchLeaseUpdate(
  input: {
    leaseId: string;
    runtimeConnectionId?: string | null;
    now?: Date;
    leaseMs?: number;
    attemptCount?: number;
  },
) {
  const now = input.now ?? new Date();
  const leaseMs = Math.max(5_000, Math.floor(input.leaseMs ?? TASK_DISPATCH_LEASE_MS));
  return {
    status: "planning" as TaskStatus,
    runtimeConnectionId: input.runtimeConnectionId ?? null,
    dispatchLeaseId: input.leaseId,
    dispatchLeaseIssuedAt: now,
    dispatchLeaseExpiresAt: new Date(now.getTime() + leaseMs),
    dispatchAckAt: null,
    dispatchAttemptCount: input.attemptCount ?? 0,
    error: null,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskDispatchLeaseAckUpdate(
  input: {
    runtimeConnectionId: string;
    leaseId: string;
    now?: Date;
    acceptedAt?: Date;
    executionDeadlineAt?: Date;
  },
) {
  const now = input.now ?? new Date();
  const acceptedAt = input.acceptedAt ?? now;
  return {
    status: "running" as TaskStatus,
    runtimeConnectionId: input.runtimeConnectionId,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: acceptedAt,
    startedAt: acceptedAt,
    ...(input.executionDeadlineAt ? { executionDeadlineAt: input.executionDeadlineAt } : {}),
    lastProgressAt: acceptedAt,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskDispatchLeaseReleaseUpdate(
  input: {
    now?: Date;
    clearRuntimeConnection?: boolean;
  } = {},
) {
  const now = input.now ?? new Date();
  return {
    status: "queued" as TaskStatus,
    runtimeConnectionId: input.clearRuntimeConnection ? null : undefined,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskDispatchExhaustedUpdate(
  input: {
    now?: Date;
    message?: string;
  } = {},
) {
  const now = input.now ?? new Date();
  const message = input.message ?? "Desktop görevi birkaç denemeden sonra teslim edilemedi.";
  return {
    status: "failed" as TaskStatus,
    summary: message,
    error: message,
    completedAt: now,
    updatedAt: now,
    queuePosition: 0,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    runtimeConnectionId: null,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskCancellationUpdate(now = new Date()) {
  return {
    status: "canceled" as TaskStatus,
    queuePosition: 0,
    canceledAt: now,
    dispatchLeaseId: null,
    dispatchLeaseIssuedAt: null,
    dispatchLeaseExpiresAt: null,
    dispatchAckAt: null,
    runtimeConnectionId: null,
    updatedAt: now,
  } satisfies Partial<typeof tasks.$inferInsert>;
}

export function buildTaskApprovalResolution(
  approvalRequest: unknown,
  input: {
    approved?: boolean;
    notes?: string;
    action?: InteractionAction;
    now?: Date;
  } = {},
) {
  const approved = input.approved ?? true;
  const existingKind = normalizeInteractionKind(
    readString(readRecord(readRecord(approvalRequest)?.interaction)?.kind) ||
      readString(readRecord(approvalRequest)?.kind),
  );
  // Eylem, zarfın türünden türetilir: bir netleştirme "onaylanmaz", yanıtlanır.
  // Eski `approved`/`notes` alanları aynen korunur.
  const action: InteractionAction =
    input.action ??
    (!approved
      ? "reject"
      : existingKind === "clarification"
        ? "answer"
        : "approve");
  const answer = action === "answer" ? (input.notes ?? null) : null;
  const resolution = {
    approved,
    notes: input.notes ?? null,
    action,
    state: approved ? (action === "answer" ? "answered" : "approved") : "rejected",
    ...(answer !== null ? { answer } : {}),
    resolvedAt: (input.now ?? new Date()).toISOString(),
    revision: approvalRequestRevision(approvalRequest),
    approvalKey: approvalRequestKey(approvalRequest) || null,
  };

  if (approvalRequest && typeof approvalRequest === "object" && !Array.isArray(approvalRequest)) {
    const request = approvalRequest as Record<string, unknown>;
    const interaction = readRecord(request.interaction);
    return {
      ...request,
      resolution,
      ...(interaction
        ? {
            interaction: {
              ...interaction,
              resolution,
            },
          }
        : {}),
    };
  }

  return {
    resolution,
  };
}

export function buildTaskApprovalResumeUpdate(
  task: {
    id?: string;
    startedAt?: Date | null;
    approvalRequest?: unknown;
  },
  input: {
    notes?: string;
    action?: InteractionAction;
    now?: Date;
  } = {},
) {
  const now = input.now ?? new Date();
  const approvalRequest = normalizeTaskApprovalRequest(task.approvalRequest, {
    taskId: readString(task.id),
    now,
  });
  const resolutionMessage = approvalRequest.interaction.kind === "clarification"
    ? "Bilgi yanıtı alındı. Görev devam ediyor."
    : "Onay alındı. Görev devam ediyor.";
  const update: Partial<typeof tasks.$inferInsert> = {
    status: "waiting_approval" as TaskStatus,
    approvalRequest: buildTaskApprovalResolution(approvalRequest, {
      notes: input.notes,
      action: input.action,
      now,
    }),
    summary: resolutionMessage,
    error: null,
    updatedAt: now,
  };

  return update;
}

export function buildTaskRuntimeUpdate(
  task: {
    startedAt?: Date | null;
    summary?: string | null;
    error?: string | null;
    approvalRequest?: unknown;
    result?: unknown;
  },
  input: {
    status: TaskStatus;
    runtimeConnectionId: string;
    summary?: string;
    error?: string;
    approvalRequest?: Record<string, unknown>;
    result?: Record<string, unknown>;
    now?: Date;
  },
) {
  const now = input.now ?? new Date();
  const updates: Partial<typeof tasks.$inferInsert> = {
    status: input.status,
    summary: input.summary ?? task.summary ?? null,
    error: input.error ?? task.error ?? null,
    approvalRequest: input.approvalRequest ?? task.approvalRequest ?? null,
    result: input.result ?? task.result ?? null,
    runtimeConnectionId: input.runtimeConnectionId,
    updatedAt: now,
  };

  if (input.status === "running" && !task.startedAt) {
    updates.startedAt = now;
  }

  if (input.status === "completed") {
    updates.completedAt = now;
    updates.queuePosition = 0;
  }

  if (input.status === "failed") {
    updates.queuePosition = 0;
  }

  if (input.status === "canceled") {
    updates.canceledAt = now;
    updates.queuePosition = 0;
  }

  return updates;
}
