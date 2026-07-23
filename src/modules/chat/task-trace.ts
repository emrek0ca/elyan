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
import { buildRouteTransparencyReason } from "./route-transparency.js";

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

  return "Uygun yol seçildi.";
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

  // Task sync sees the durable DB result (flat metadata), while feed clients
  // receive the public `brain` projection. Read both shapes so research/RAG is
  // never lost from the execution transcript during either path.
  const readBrainOrResultNumber = (key: string) =>
    readNumber(brain, key) ?? readNumber(result, key) ?? 0;
  const readBrainOrResultBoolean = (key: string) =>
    readBoolean(brain, key) ?? readBoolean(result, key) ?? false;

  const hintCount =
    readStringList(context, "personalizationHints").length +
    readStringList(context, "projectHints").length +
    readStringList(context, "styleHints").length +
    readStringList(context, "technicalHints").length +
    readStringList(context, "safetyHints").length;

  return {
    hintCount,
    attachmentContextUsed: readBrainOrResultBoolean("attachmentContextUsed"),
    documentSourceCount: readBrainOrResultNumber("documentSourceCount"),
    retrievalResultCount: readBrainOrResultNumber("retrievalResultCount"),
    webSourceCount: readBrainOrResultNumber("webSourceCount"),
    groundingUsed:
      readBrainOrResultBoolean("groundingUsed") ||
      readBrainOrResultBoolean("webGroundingUsed"),
  };
}

function describeContext(task: TaskTraceSource): {
  needed: boolean;
  completed: boolean;
  detail?: string;
} {
  const signals = contextSignals(task);
  const totalSources =
    signals.documentSourceCount +
    signals.retrievalResultCount +
    signals.webSourceCount;
  if (
    signals.attachmentContextUsed ||
    signals.documentSourceCount > 0 ||
    signals.retrievalResultCount > 0
  ) {
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
  tools: Array<{ name: string; ok: boolean; resultCount: number | null; errorCode: string | null; durationMs: number | null }>;
};

const TOOL_APP_LABELS: Record<string, string> = {
  document_read: "Belge",
  document_write: "Belge",
  math_solve: "Hesap",
  presentation_write: "Sunum",
  spreadsheet_write: "Tablo",
  text_analyze: "Analiz",
  web_research: "Web",
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
    const tools: ToolFlowTraceSummary["tools"] = [];
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
      tools.push({
        name,
        ok: readBoolean(toolRecord, "ok") === true,
        resultCount: readNumber(toolRecord, "resultCount"),
        errorCode: readString(toolRecord, "errorCode"),
        durationMs: readNumber(toolRecord, "durationMs"),
      });
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

function publicToolLabel(name: string): string {
  const tool = name.trim().toLowerCase();
  if (tool === "document_read") return "Belgeyi okuyorum…";
  if (tool === "math_solve") return "Hesabı çözüyorum…";
  if (tool === "text_analyze") return "Bağlamı analiz ediyorum…";
  if (tool === "document_write") return "Belgeyi hazırlıyorum…";
  if (tool === "spreadsheet_write") return "Tabloyu hazırlıyorum…";
  if (tool === "presentation_write") return "Sunumu hazırlıyorum…";
  if (tool === "web_research") return "Web'de araştırıyorum…";
  if (tool === "web.search" || tool.startsWith("web.")) return "Web'de araştırıyorum…";
  if (tool === "gmail.search" || tool === "gmail.read") return "Gelen kutunu tarıyorum…";
  if (tool.startsWith("gmail.") && /(send|draft|create|update)/.test(tool)) return "E-posta işlemini hazırlıyorum…";
  if ((tool.startsWith("drive.") || tool.startsWith("google-drive.")) && /(upload|create|update|write|move|delete)/.test(tool)) return "Drive işlemini hazırlıyorum…";
  if (tool.startsWith("drive.") || tool.startsWith("google-drive.")) return "Dosyalarını tarıyorum…";
  if ((tool.startsWith("calendar.") || tool.startsWith("gcal.")) && /(create|add|update|delete|write)/.test(tool)) return "Takvim işlemini hazırlıyorum…";
  if (tool.startsWith("calendar.") || tool.startsWith("gcal.")) return "Takvimini kontrol ediyorum…";
  if (tool.startsWith("slack.") && /(send|post|create|update)/.test(tool)) return "Slack işlemini hazırlıyorum…";
  if (tool.startsWith("notion.") && /(create|update|write|append|delete)/.test(tool)) return "Notion işlemini hazırlıyorum…";
  if (tool.startsWith("github.") && /(create|update|comment|merge|close)/.test(tool)) return "GitHub işlemini hazırlıyorum…";
  if (tool.startsWith("memory.")) return "Hatırladıklarımı kontrol ediyorum…";
  if (tool.startsWith("goals.")) return "Hedef durumunu kontrol ediyorum…";
  return "İlgili bilgileri kontrol ediyorum…";
}

function publicToolResult(tool: ToolFlowTraceSummary["tools"][number]): string {
  if (!tool.ok) {
    const code = String(tool.errorCode ?? "").toLowerCase();
    if (/auth|oauth|credential|token|connect/.test(code)) return "Bağlantı izni gerektiği için bu adım tamamlanamadı.";
    if (/permission|forbidden|scope|denied/.test(code)) return "Bu işlem için gerekli izin bulunamadı.";
    if (/timeout|timed_out|unavailable|network|rate_limit/.test(code)) return "Hizmete şu anda ulaşılamadığı için bu adım tamamlanamadı.";
    return "Bu adım tamamlanamadı.";
  }
  if (tool.name === "text_analyze") return "Analiz tamamlandı.";
  if (tool.name === "math_solve") return "Hesap tamamlandı.";
  if (tool.name === "document_read") return "Belge okundu.";
  if (tool.name === "document_write") return "Belge hazırlandı.";
  if (tool.name === "spreadsheet_write") return "Tablo hazırlandı.";
  if (tool.name === "presentation_write") return "Sunum hazırlandı.";
  const normalizedName = tool.name.trim().toLowerCase();
  if (normalizedName.startsWith("gmail.") && /(send|draft|create|update)/.test(normalizedName)) return "E-posta işlemi hazır.";
  if ((normalizedName.startsWith("drive.") || normalizedName.startsWith("google-drive.")) && /(upload|create|update|write|move|delete)/.test(normalizedName)) return "Drive işlemi tamamlandı.";
  if ((normalizedName.startsWith("calendar.") || normalizedName.startsWith("gcal.")) && /(create|add|update|delete|write)/.test(normalizedName)) return "Takvim işlemi hazır.";
  if (normalizedName.startsWith("slack.") && /(send|post|create|update)/.test(normalizedName)) return "Slack işlemi hazır.";
  if (normalizedName.startsWith("notion.") && /(create|update|write|append|delete)/.test(normalizedName)) return "Notion işlemi tamamlandı.";
  if (normalizedName.startsWith("github.") && /(create|update|comment|merge|close)/.test(normalizedName)) return "GitHub işlemi tamamlandı.";
  if (tool.resultCount == null) return "Adım tamamlandı.";
  if (tool.name === "gmail.search" || tool.name === "gmail.read") return `${tool.resultCount} e-posta bulundu.`;
  if (tool.name === "web.search" || tool.name === "web_research" || tool.name.startsWith("web.")) return `${tool.resultCount} kaynak bulundu.`;
  return `${tool.resultCount} sonuç bulundu.`;
}

function describeTool(task: TaskTraceSource) {
  const routeDecision = extractTaskRouteDecision(task.payload);
  const result = readRecord(task.result);
  const operator = readRecord(result?.operator);
  const toolFlow = readToolFlow(result);
  const signals = contextSignals(task);
  const usedDesktop =
    routeDecision?.taskRoute?.operationalRoute === "desktop_runtime" ||
    routeDecision?.route === "desktop_runtime";
  const activeApp = readString(operator, "activeApp");

  // Sunucu-taraflı connector/agent araçları (Gmail/Takvim/Drive vb.): önceden
  // operator olmadığı için "Araç gerekmedi" görünüyordu. Artık gerçek çağrı
  // görünür.
  if (toolFlow) {
    const toolDetail = describeToolFlow(toolFlow);
    const webAlreadyReported = toolFlow.tools.some((tool) =>
      tool.name.trim().toLowerCase().startsWith("web."),
    );
    return {
      needed: true,
      detail:
        signals.webSourceCount > 0 && !webAlreadyReported
          ? `${toolDetail}; Web · ${signals.webSourceCount} kaynak`
          : toolDetail,
    };
  }

  if (signals.webSourceCount > 0) {
    return {
      needed: true,
      detail: `Web · ${signals.webSourceCount} kaynak`,
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
    default:
      return "Adım yürütülüyor";
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
    default:
      return "Adım yürütülüyor.";
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
  const routeReason = buildRouteTransparencyReason(routeDecision);
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
    stableBlockId: `task_trace_${input.task.id}`,
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
    ...(routeReason ? { routeReason } : {}),
    ...(activeStep ? { activeStepId: activeStep.id } : {}),
    steps,
  };
}

export function enrichTaskTraceWithAgentPlan(input: {
  trace: ElyanTaskTraceBlock;
  agentPlan: unknown;
  toolFlow: unknown;
  approval: unknown;
}): ElyanTaskTraceBlock {
  const plan = readRecord(input.agentPlan);
  const rawSteps = Array.isArray(plan?.steps) ? plan.steps : [];
  const flow = readRecord(input.toolFlow);
  const toolResults = Array.isArray(flow?.tools) ? flow.tools : [];
  const approval = readRecord(input.approval);
  const planSteps = rawSteps.flatMap((value, index) => {
    const step = readRecord(value);
    const request = readRecord(step?.tool_request);
    const id = readString(step, "id") ?? `step_${index + 1}`;
    const fallbackLabel = readString(step, "title");
    const tool = readString(request, "tool");
    if (!fallbackLabel || !tool || !/^[a-zA-Z0-9_-]{1,80}$/.test(id)) return [];
    const result = toolResults.map(readRecord).find((item) => readString(item, "name") === tool);
    const stepApproval = approval && readString(approval, "tool") === tool ? approval : null;
    const status: ElyanTaskTraceStepStatus = stepApproval
      ? "waiting_approval"
      : result ? (result.ok === true ? "completed" : "failed") : "pending";
    const publicResult = result ? publicToolResult({
      name: tool,
      ok: result.ok === true,
      resultCount: readNumber(result, "resultCount"),
      errorCode: readString(result, "errorCode"),
      durationMs: readNumber(result, "durationMs"),
    }) : undefined;
    const durationMs = readNumber(result ?? null, "durationMs");
    const lines = Array.isArray(stepApproval?.lines) ? stepApproval.lines.flatMap((line) => {
      const record = readRecord(line);
      const label = readString(record, "label");
      const value = readString(record, "value");
      return label && value != null ? [{ label, value }] : [];
    }) : [];
    return [{
      id,
      label: publicToolLabel(tool),
      status,
      tool,
      ...(publicResult ? { detail: publicResult, resultSummary: publicResult } : {}),
      ...(durationMs != null && durationMs >= 0 ? { durationMs } : {}),
      ...(stepApproval ? { approval: {
        token: readString(stepApproval, "token")!,
        tool,
        title: readString(stepApproval, "title") ?? fallbackLabel,
        appLabel: readString(stepApproval, "appLabel") ?? "",
        expiresAt: readNumber(stepApproval, "expiresAt"),
        lines,
      } } : {}),
    } satisfies ElyanTaskTraceStep];
  });
  if (planSteps.length === 0) return input.trace;
  const waiting = planSteps.some((step) => step.status === "waiting_approval");
  const failed = planSteps.some((step) => step.status === "failed");
  return {
    ...input.trace,
    status: waiting ? "waiting_approval" : failed ? "failed" : input.trace.status,
    activeStepId: planSteps.find((step) => step.status === "waiting_approval" || step.status === "pending")?.id ?? planSteps.at(-1)?.id,
    steps: planSteps,
  };
}

export function advanceTaskTraceApproval(input: {
  blocks: unknown;
  completedTool: string;
  nextApproval?: Record<string, unknown> | null;
}): unknown[] {
  if (!Array.isArray(input.blocks)) return [];
  const nextTool = readString(input.nextApproval ?? null, "tool");
  return input.blocks.map((value) => {
    const block = readRecord(value);
    if (block?.type !== "task_trace" || !Array.isArray(block.steps)) return value;
    const steps = block.steps.map((value) => {
      const step = readRecord(value);
      const approval = readRecord(step?.approval);
      const approvalTool = readString(approval, "tool");
      const stepTool = readString(step, "tool") ?? approvalTool;
      if (approvalTool === input.completedTool) {
        const { approval: _approval, ...rest } = step!;
        return { ...rest, status: "completed", detail: "Adım tamamlandı.", resultSummary: "Adım tamamlandı." };
      }
      if (input.nextApproval && (stepTool === nextTool || approvalTool === nextTool)) {
        return { ...step, status: "waiting_approval", approval: input.nextApproval };
      }
      return value;
    });
    return {
      ...block,
      status: input.nextApproval ? "waiting_approval" : "completed",
      activeStepId: input.nextApproval ? steps.find((step) => readRecord(step)?.status === "waiting_approval")?.id : steps.at(-1)?.id,
      steps,
    };
  });
}
