import type {
  ElyanTaskTraceBlock,
  ElyanTaskTraceStatus,
  ElyanTaskTraceStep,
  ElyanTaskTraceStepId,
  ElyanTaskTraceStepStatus,
  TaskStatus,
} from "../../contracts/domain.js";
import {
  extractTaskRouteDecision,
  getPayloadMetadata,
} from "../tasks/service-helpers.js";

type TaskTraceSource = {
  id: string;
  status?: TaskStatus;
  payload?: unknown;
  result?: unknown;
  summary?: string | null;
  error?: string | null;
  createdAt?: Date | null;
  updatedAt?: Date | null;
  completedAt?: Date | null;
};

const STEP_LABELS: Record<ElyanTaskTraceStepId, string> = {
  intent: "İstek analizi",
  route: "Yönlendirme",
  plan: "Plan",
  context: "Bağlam",
  tool: "Araç akışı",
  verify: "Kontrol",
  response: "Yanıt",
};

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

function readBoolean(
  record: Record<string, unknown> | null,
  key: string,
): boolean | null {
  const value = record?.[key];
  return typeof value === "boolean" ? value : null;
}

function readNumber(
  record: Record<string, unknown> | null,
  key: string,
): number | null {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readStringList(
  record: Record<string, unknown> | null,
  key: string,
): string[] {
  const value = record?.[key];
  return Array.isArray(value)
    ? value
        .map((item) => (typeof item === "string" ? item.trim() : ""))
        .filter(Boolean)
    : [];
}

function compactDetail(
  value: string | null | undefined,
  maxLength = 120,
): string | undefined {
  const normalized = String(value ?? "")
    .replace(/\s+/g, " ")
    .trim();
  if (!normalized) {
    return undefined;
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}…`;
}

function mapTraceStatus(
  status: TaskStatus | null | undefined,
): ElyanTaskTraceStatus {
  switch (status) {
    case "completed":
      return "completed";
    case "failed":
    case "canceled":
      return "failed";
    case "waiting_approval":
      return "waiting_approval";
    case "queued":
    case "planning":
    case "running":
    case undefined:
    case null:
      return "running";
  }
}

function isoOrNull(value: Date | null | undefined): string | undefined {
  return value instanceof Date && !Number.isNaN(value.getTime())
    ? value.toISOString()
    : undefined;
}

function describeIntent(intent: string | null): string | undefined {
  const normalized = String(intent ?? "")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return undefined;
  }
  const known: Record<string, string> = {
    chat: "İstek netleşti.",
    research: "Araştırma yönü netleşti.",
    coding: "Teknik istek netleşti.",
    writing: "Yazı akışı netleşti.",
    document_read: "Belge odağı netleşti.",
    image_read: "Görsel odağı netleşti.",
    quantum: "Kuantum odağı netleşti.",
  };
  return known[normalized] ?? "İstek netleşti.";
}

function describeRoute(
  routeDecision: ReturnType<typeof extractTaskRouteDecision>,
): string | undefined {
  if (!routeDecision) {
    return undefined;
  }

  if (
    routeDecision.taskRoute?.operationalRoute === "desktop_runtime" ||
    routeDecision.route === "desktop_runtime"
  ) {
    return compactDetail(
      routeDecision.taskRoute?.needsPrivateDesktopData
        ? "Masaüstü yolu seçildi."
        : "Masaüstü çalışma yolu seçildi.",
    );
  }

  if (routeDecision.route === "server_brain") {
    return "Yanıt yolu seçildi.";
  }

  if (routeDecision.route === "pairing_required") {
    return "Masaüstü bağlantısı gerekiyor.";
  }

  return compactDetail(
    routeDecision.reason ??
      routeDecision.failClosedReason ??
      "Uygun yol seçildi.",
  );
}

function describePlan(
  routeDecision: ReturnType<typeof extractTaskRouteDecision>,
): string | undefined {
  const executionPlan = routeDecision?.taskRoute?.executionPlan ?? [];
  if (executionPlan.length > 0) {
    return "Plan hazır.";
  }
  if (routeDecision?.selectedWorkload) {
    return "Yanıt tonu ayarlandı.";
  }
  return undefined;
}

function fallbackTerminalDetail(
  status: ElyanTaskTraceStatus,
  value: {
    completed?: string;
    waitingApproval?: string;
  },
): string | undefined {
  if (status === "completed") {
    return value.completed;
  }
  if (status === "waiting_approval") {
    return value.waitingApproval ?? value.completed;
  }
  return undefined;
}

function contextSignals(task: TaskTraceSource) {
  const payloadMetadata = getPayloadMetadata(readRecord(task.payload) ?? {});
  const understanding = readRecord(payloadMetadata.understanding);
  const context = readRecord(understanding?.context);
  const result = readRecord(task.result);
  const brain = readRecord(result?.brain);

  const hintCount =
    readStringList(context, "personalizationHints").length +
    readStringList(context, "projectHints").length +
    readStringList(context, "styleHints").length +
    readStringList(context, "technicalHints").length +
    readStringList(context, "safetyHints").length;

  return {
    hintCount,
    attachmentContextUsed: readBoolean(brain, "attachmentContextUsed") === true,
    documentSourceCount: readNumber(brain, "documentSourceCount") ?? 0,
    webSourceCount: readNumber(brain, "webSourceCount") ?? 0,
    groundingUsed:
      readBoolean(brain, "groundingUsed") === true ||
      readBoolean(brain, "webGroundingUsed") === true,
  };
}

function describeContext(task: TaskTraceSource): {
  needed: boolean;
  completed: boolean;
  detail?: string;
} {
  const signals = contextSignals(task);
  const totalSources = signals.documentSourceCount + signals.webSourceCount;
  if (signals.attachmentContextUsed || signals.documentSourceCount > 0) {
    return {
      needed: true,
      completed: true,
      detail: "Belge bağlamı hazır.",
    };
  }

  if (signals.webSourceCount > 0 || signals.groundingUsed) {
    return {
      needed: true,
      completed: true,
      detail: totalSources > 0 ? "Kaynak bağlamı hazır." : "Bağlam hazır.",
    };
  }

  if (signals.hintCount > 0) {
    return {
      needed: true,
      completed: true,
      detail: "Kişisel bağlam hazır.",
    };
  }

  return {
    needed: false,
    completed: false,
    detail: "Bağlam dengede.",
  };
}

type ToolFlowTraceSummary = {
  okCount: number;
  tools: Array<{ name: string; resultCount: number | null }>;
};

const TOOL_APP_LABELS: Record<string, string> = {
  gmail: "Gmail",
  calendar: "Takvim",
  "google-calendar": "Takvim",
  gcal: "Takvim",
  drive: "Drive",
  "google-drive": "Drive",
  notion: "Notion",
  linear: "Linear",
  github: "GitHub",
  slack: "Slack",
};

function appLabelForTool(name: string): string {
  const normalized = String(name ?? "")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return "Araç";
  }
  const prefix = normalized.split(/[.\/:_-]/)[0] || normalized;
  return (
    TOOL_APP_LABELS[normalized] ??
    TOOL_APP_LABELS[prefix] ??
    (prefix ? `${prefix.charAt(0).toUpperCase()}${prefix.slice(1)}` : "Araç")
  );
}

// task-trace kartında görünen araç akışı özeti. Kaynak, ham task result'ın
// düz `toolFlow` alanı (server_brain completion) veya feed-şekilli
// `brain.toolFlow` olabilir; her iki şekli de savunmacı okur.
function readToolFlow(
  result: Record<string, unknown> | null,
): ToolFlowTraceSummary | null {
  if (!result) {
    return null;
  }
  const brain = readRecord(result.brain);
  for (const candidate of [result.toolFlow, brain?.toolFlow]) {
    const record = readRecord(candidate);
    if (!record) {
      continue;
    }
    const rawTools = Array.isArray(record.tools) ? record.tools : [];
    const tools: Array<{ name: string; resultCount: number | null }> = [];
    let derivedOkCount = 0;
    for (const item of rawTools) {
      const toolRecord = readRecord(item);
      const name =
        readString(toolRecord, "name") ?? readString(toolRecord, "tool");
      if (!name) {
        continue;
      }
      if (readBoolean(toolRecord, "ok") === true) {
        derivedOkCount += 1;
      }
      tools.push({ name, resultCount: readNumber(toolRecord, "resultCount") });
      if (tools.length >= 8) {
        break;
      }
    }
    if (tools.length === 0) {
      continue;
    }
    const declaredOkCount = readNumber(record, "okCount");
    return {
      okCount: declaredOkCount != null ? declaredOkCount : derivedOkCount,
      tools,
    };
  }
  return null;
}

function describeToolFlow(toolFlow: ToolFlowTraceSummary): string {
  const appLabels: string[] = [];
  let totalResults = 0;
  let hasResultCount = false;
  for (const tool of toolFlow.tools) {
    const label = appLabelForTool(tool.name);
    if (!appLabels.includes(label)) {
      appLabels.push(label);
    }
    if (typeof tool.resultCount === "number") {
      hasResultCount = true;
      totalResults += tool.resultCount;
    }
  }
  const label = appLabels.slice(0, 3).join(", ") || "Araç";
  if (toolFlow.okCount === 0) {
    return `${label} denendi`;
  }
  if (hasResultCount) {
    return `${label} · ${totalResults} sonuç`;
  }
  return `${label} kullanıldı`;
}

function describeTool(task: TaskTraceSource) {
  const routeDecision = extractTaskRouteDecision(task.payload);
  const result = readRecord(task.result);
  const operator = readRecord(result?.operator);
  const toolFlow = readToolFlow(result);
  const usedDesktop =
    routeDecision?.taskRoute?.operationalRoute === "desktop_runtime" ||
    routeDecision?.route === "desktop_runtime";
  const activeApp = readString(operator, "activeApp");

  // Sunucu-taraflı connector/agent araçları (Gmail/Takvim/Drive vb.): önceden
  // operator olmadığı için "Araç gerekmedi" görünüyordu. Artık gerçek çağrı
  // görünür.
  if (toolFlow) {
    return {
      needed: true,
      detail: describeToolFlow(toolFlow),
    };
  }

  if (usedDesktop || operator) {
    return {
      needed: true,
      detail: activeApp ? "Araç akışı tamamlandı." : "Araç akışı hazır.",
    };
  }

  return {
    needed: false,
    detail: "Araç gerekmedi.",
  };
}

function describeVerify(task: TaskTraceSource): {
  completed: boolean;
  detail?: string;
} {
  const result = readRecord(task.result);
  const operator = readRecord(result?.operator);
  const brain = readRecord(result?.brain);
  const lastVerificationOk = readBoolean(operator, "lastVerificationOk");
  const qualityPolicyApplied = readBoolean(brain, "qualityPolicyApplied");

  if (lastVerificationOk === true || qualityPolicyApplied === true) {
    return {
      completed: true,
      detail: "Kontrol tamam.",
    };
  }

  return {
    completed: false,
    detail:
      task.status === "failed"
        ? compactDetail(task.error ?? "Doğrulama tamamlanamadı.")
        : "Kontrol sürüyor.",
  };
}

function buildStep(input: {
  id: ElyanTaskTraceStepId;
  status: ElyanTaskTraceStepStatus;
  detail?: string;
  task: TaskTraceSource;
  startedAt?: Date | null;
  completedAt?: Date | null;
}): ElyanTaskTraceStep {
  return {
    id: input.id,
    label: STEP_LABELS[input.id],
    status: input.status,
    ...(compactDetail(input.detail)
      ? { detail: compactDetail(input.detail) }
      : {}),
    ...(isoOrNull(input.startedAt ?? input.task.createdAt)
      ? { startedAt: isoOrNull(input.startedAt ?? input.task.createdAt) }
      : {}),
    ...(isoOrNull(input.completedAt)
      ? { completedAt: isoOrNull(input.completedAt) }
      : {}),
  };
}

function resolveFailureStep(
  task: TaskTraceSource,
  toolNeeded: boolean,
): ElyanTaskTraceStepId {
  const normalizedError = String(task.error ?? "")
    .trim()
    .toLowerCase();
  if (normalizedError.includes("approval")) {
    return "verify";
  }
  if (
    normalizedError.includes("route") ||
    normalizedError.includes("desktop")
  ) {
    return "route";
  }
  if (normalizedError.includes("tool") || normalizedError.includes("runtime")) {
    return "tool";
  }
  return toolNeeded ? "tool" : "response";
}

function firstStepWithStatus(
  steps: ElyanTaskTraceStep[],
  status: ElyanTaskTraceStepStatus,
): ElyanTaskTraceStep | undefined {
  return steps.find((step) => step.status === status);
}

function lastCompletedStep(
  steps: ElyanTaskTraceStep[],
): ElyanTaskTraceStep | undefined {
  const completed = steps.filter((step) => step.status === "completed");
  return completed.length > 0 ? completed[completed.length - 1] : undefined;
}

function stepLabelForPhase(stepId: ElyanTaskTraceStepId | undefined): string {
  switch (stepId) {
    case "intent":
      return "İsteği okuyor";
    case "route":
      return "Yolu seçiyor";
    case "plan":
      return "Planı kuruyor";
    case "context":
      return "Bağlamı bağlıyor";
    case "tool":
      return "Araçları işletiyor";
    case "verify":
      return "Son kontrol";
    case "response":
      return "Yanıtı yazıyor";
    case undefined:
      return "Akışı hazırlıyor";
  }
}

function activeStepSummary(stepId: ElyanTaskTraceStepId | undefined): string {
  switch (stepId) {
    case "intent":
      return "İstek netleşiyor.";
    case "route":
      return "Yol seçiliyor.";
    case "plan":
      return "Plan kuruluyor.";
    case "context":
      return "Bağlam bağlanıyor.";
    case "tool":
      return "Araç çalışıyor.";
    case "verify":
      return "Yanıt kontrol ediliyor.";
    case "response":
      return "Cevap yazılıyor.";
    case undefined:
      return "Yanıt adım adım hazırlanıyor.";
  }
}

function buildProgressLabel(
  status: ElyanTaskTraceStatus,
  activeStep: ElyanTaskTraceStep | undefined,
  completedStep: ElyanTaskTraceStep | undefined,
): string {
  if (status === "failed") {
    return "Akış durdu";
  }
  if (status === "waiting_approval") {
    return "Onay bekliyor";
  }
  if (status === "completed") {
    return "Yanıt hazır";
  }
  return stepLabelForPhase(activeStep?.id ?? completedStep?.id);
}

function buildTraceSummary(input: {
  status: ElyanTaskTraceStatus;
  activeStep?: ElyanTaskTraceStep;
  completedStep?: ElyanTaskTraceStep;
  contextNeeded: boolean;
  toolNeeded: boolean;
  error?: string | null;
}): string {
  if (input.status === "failed") {
    return (
      compactDetail(input.error ?? "İşlem güvenli şekilde durduruldu.", 180) ??
      "İşlem güvenli şekilde durduruldu."
    );
  }
  if (input.status === "waiting_approval") {
    return "Devam etmek için kullanıcı onayı gerekiyor.";
  }
  if (input.status === "completed") {
    if (input.toolNeeded && input.contextNeeded) {
      return "Bağlam ve araç akışı tamam.";
    }
    if (input.contextNeeded) {
      return "Bağlam işlendi.";
    }
    if (input.toolNeeded) {
      return "Araç akışı tamam.";
    }
    return "Kontrol tamam.";
  }
  return (
    compactDetail(
      input.activeStep?.detail ??
        activeStepSummary(input.activeStep?.id) ??
        input.completedStep?.detail,
      180,
    ) ?? "Yanıt adım adım hazırlanıyor."
  );
}

export function buildTaskTraceBlock(input: {
  task: TaskTraceSource;
  assistantContent?: string | null;
}): ElyanTaskTraceBlock {
  const routeDecision = extractTaskRouteDecision(input.task.payload);
  const payloadMetadata = getPayloadMetadata(
    readRecord(input.task.payload) ?? {},
  );
  const understanding = readRecord(payloadMetadata.understanding);
  const intentRecord = readRecord(understanding?.intent);
  const intent =
    routeDecision?.intent ??
    readString(intentRecord, "primaryIntent") ??
    readString(intentRecord, "intent");
  const planDetail = describePlan(routeDecision);
  const context = describeContext(input.task);
  const tool = describeTool(input.task);
  const verify = describeVerify(input.task);
  const traceStatus = mapTraceStatus(input.task.status);
  const assistantContent = String(input.assistantContent ?? "").trim();
  const completedAt = input.task.completedAt ?? input.task.updatedAt ?? null;
  const runningLike =
    input.task.status == null ||
    input.task.status === "queued" ||
    input.task.status === "planning" ||
    input.task.status === "running";
  const responseHasVisibleText =
    assistantContent.length > 0 &&
    assistantContent.toLowerCase() != "hazırlanıyor";
  const failureStep =
    traceStatus === "failed"
      ? resolveFailureStep(input.task, tool.needed)
      : null;
  const terminalSuccess =
    traceStatus === "completed" || traceStatus === "waiting_approval";

  const steps: ElyanTaskTraceStep[] = [
    buildStep({
      id: "intent",
      status:
        intent != null
          ? "completed"
          : runningLike
            ? "running"
            : terminalSuccess
              ? "completed"
              : "skipped",
      detail:
        describeIntent(intent) ??
        fallbackTerminalDetail(traceStatus, {
          completed: "İstek netleşti.",
        }),
      task: input.task,
      completedAt:
        intent != null || terminalSuccess ? input.task.updatedAt : null,
    }),
    buildStep({
      id: "route",
      status:
        failureStep === "route"
          ? "failed"
          : routeDecision || terminalSuccess
            ? "completed"
            : runningLike
              ? "running"
              : "skipped",
      detail:
        failureStep === "route"
          ? compactDetail(input.task.error ?? routeDecision?.failClosedReason)
          : (describeRoute(routeDecision) ??
            fallbackTerminalDetail(traceStatus, {
              completed: "Yol seçildi.",
              waitingApproval: "Yol beklemede.",
            })),
      task: input.task,
      completedAt:
        routeDecision != null || terminalSuccess ? input.task.updatedAt : null,
    }),
    buildStep({
      id: "plan",
      status:
        failureStep === "route"
          ? "skipped"
          : failureStep === "plan"
            ? "failed"
            : planDetail != null || terminalSuccess
              ? "completed"
              : input.task.status === "planning" ||
                  input.task.status === "queued"
                ? "running"
                : "skipped",
      detail:
        failureStep === "plan"
          ? compactDetail(input.task.error)
          : (planDetail ??
            fallbackTerminalDetail(traceStatus, {
              completed: "Plan hazır.",
              waitingApproval: "Plan hazır.",
            })),
      task: input.task,
      completedAt:
        planDetail != null || terminalSuccess ? input.task.updatedAt : null,
    }),
    buildStep({
      id: "context",
      status:
        failureStep === "context"
          ? "failed"
          : context.needed && context.completed
            ? "completed"
            : context.needed && traceStatus === "running"
              ? "running"
              : context.needed
                ? "pending"
                : "skipped",
      detail:
        failureStep === "context"
          ? compactDetail(input.task.error)
          : context.detail,
      task: input.task,
      completedAt: context.completed ? input.task.updatedAt : null,
    }),
    buildStep({
      id: "tool",
      status:
        failureStep === "tool"
          ? "failed"
          : tool.needed &&
              (traceStatus === "completed" ||
                traceStatus === "waiting_approval")
            ? "completed"
            : tool.needed && traceStatus === "running"
              ? "running"
              : tool.needed
                ? "pending"
                : "skipped",
      detail:
        failureStep === "tool" ? compactDetail(input.task.error) : tool.detail,
      task: input.task,
      completedAt:
        tool.needed &&
        (traceStatus === "completed" || traceStatus === "waiting_approval")
          ? input.task.updatedAt
          : null,
    }),
    buildStep({
      id: "verify",
      status:
        failureStep === "verify"
          ? "failed"
          : verify.completed || traceStatus === "completed"
            ? "completed"
            : traceStatus === "failed"
              ? "failed"
              : traceStatus === "running" || traceStatus === "waiting_approval"
                ? "running"
                : "pending",
      detail:
        failureStep === "verify"
          ? compactDetail(input.task.error)
          : (verify.detail ??
            fallbackTerminalDetail(traceStatus, {
              completed: "Kontrol tamam.",
            })),
      task: input.task,
      completedAt:
        verify.completed || traceStatus === "completed"
          ? input.task.updatedAt
          : null,
    }),
    buildStep({
      id: "response",
      status:
        failureStep === "response"
          ? "failed"
          : traceStatus === "completed" || traceStatus === "waiting_approval"
            ? "completed"
            : responseHasVisibleText
              ? "running"
              : traceStatus === "failed"
                ? "failed"
                : "pending",
      detail:
        failureStep === "response"
          ? compactDetail(input.task.error ?? "Yanıt hazırlanamadı.")
          : traceStatus === "completed"
            ? "Yanıt hazır."
            : traceStatus === "waiting_approval"
              ? "Onay bekliyor."
              : "Yanıt hazırlanıyor.",
      task: input.task,
      completedAt:
        traceStatus === "completed" || traceStatus === "waiting_approval"
          ? completedAt
          : null,
    }),
  ];
  const activeStep =
    firstStepWithStatus(steps, "running") ??
    firstStepWithStatus(steps, "pending");
  const completedStep = lastCompletedStep(steps);
  const progressLabel = buildProgressLabel(
    traceStatus,
    activeStep,
    completedStep,
  );
  const phase = activeStep?.id ?? completedStep?.id ?? "response";
  const summary = buildTraceSummary({
    status: traceStatus,
    activeStep,
    completedStep,
    contextNeeded: context.needed,
    toolNeeded: tool.needed,
    error: input.task.error,
  });

  return {
    type: "task_trace",
    taskId: input.task.id,
    status: traceStatus,
    title:
      traceStatus === "completed"
        ? "Görev tamamlandı"
        : traceStatus === "failed"
          ? "Görev tamamlanamadı"
          : traceStatus === "waiting_approval"
            ? "Onay bekleniyor"
            : "Görev yürütülüyor",
    phase,
    summary,
    progressLabel,
    ...(activeStep ? { activeStepId: activeStep.id } : {}),
    steps,
  };
}
