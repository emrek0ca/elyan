import type {
  ElyanTaskTraceBlock,
  ElyanTaskTraceStatus,
  ElyanTaskTraceStep,
  ElyanTaskTraceStepId,
  ElyanTaskTraceStepStatus,
  TaskStatus,
} from "../../contracts/domain.js";
import { DESKTOP_CAPABILITY_MANIFEST } from "../tasks/desktop-capability-manifest.js";
import {
  extractTaskRouteDecision,
  getPayloadMetadata,
} from "../tasks/service-helpers.js";
import { buildRouteTransparencyReason } from "./route-transparency.js";
import { isDispatchWidgetType } from "../../contracts/assistant-block-schemas.js";

type TaskTraceSource = {
  id: string;
  status?: TaskStatus;
  payload?: unknown;
  result?: unknown;
  approvalRequest?: unknown;
  summary?: string | null;
  error?: string | null;
  createdAt?: Date | null;
  updatedAt?: Date | null;
  completedAt?: Date | null;
  dispatchLeaseIssuedAt?: Date | null;
  dispatchAckAt?: Date | null;
  runtimeConnectionId?: string | null;
};

function decorateLifecycleFields(
  block: ElyanTaskTraceBlock,
  task: TaskTraceSource,
): ElyanTaskTraceBlock {
  const approval = readRecord(task.approvalRequest);
  const interaction = readRecord(approval?.interaction);
  const interactionKind = readString(interaction, "kind");
  const kind = interactionKind === "clarification" ? "clarification" : "permission";
  const question = compactDetail(
    readString(approval, "question") ?? readString(approval, "message"),
    500,
  );
  const declaredActions = readStringList(approval, "availableActions");
  const result = readRecord(task.result);
  const resultError = readRecord(result?.error);
  const errorMessage = compactDetail(
    readString(resultError, "message") ?? task.error,
    500,
  );
  const retryable = readBoolean(resultError, "retryable") === true;
  const rawArtifacts = Array.isArray(result?.artifacts) ? result.artifacts : [];
  const artifacts = rawArtifacts.flatMap((value) => {
    const artifact = readRecord(value);
    if (!artifact) return [];
    const title = compactDetail(
      readString(artifact, "title") ??
        readString(artifact, "name") ??
        readString(artifact, "fileName"),
      180,
    );
    if (!title) return [];
    const id = compactDetail(readString(artifact, "id"), 255);
    const artifactKind = compactDetail(readString(artifact, "kind"), 80);
    const path = compactDetail(readString(artifact, "path"), 1_000);
    const url = compactDetail(readString(artifact, "url"), 2_000);
    return [{
      ...(id ? { id } : {}),
      title,
      ...(artifactKind ? { kind: artifactKind } : {}),
      ...(path ? { path } : {}),
      ...(url ? { url } : {}),
    }];
  }).slice(0, 12);
  const availableActions = block.status === "waiting_approval"
    ? (declaredActions.length > 0
        ? declaredActions
        : kind === "clarification"
          ? ["answer"]
          : ["approve", "reject"])
    : block.status === "failed" && retryable
      ? ["retry"]
      : [];
  const safeActions = availableActions.filter(
    (action): action is "approve" | "reject" | "answer" | "retry" =>
      ["approve", "reject", "answer", "retry"].includes(action),
  );
  return {
    ...block,
    ...(block.status === "waiting_approval"
      ? {
          interaction: {
            kind,
            ...(question ? { question } : {}),
          },
          // A clarification is a question, not a computer permission.
          needsApproval: kind === "permission",
        }
      : {}),
    verification: block.verification ?? {
      status:
        block.status === "completed"
          ? "passed"
          : block.status === "failed"
            ? "failed"
            : "pending",
      ...(block.summary ? { summary: block.summary } : {}),
    },
    ...(artifacts.length > 0 ? { artifacts } : {}),
    ...(block.status === "failed" && errorMessage
      ? {
          error: {
            code:
              compactDetail(readString(resultError, "code"), 120) ??
              "TASK_EXECUTION_FAILED",
            message: errorMessage,
            retryable,
          },
        }
      : {}),
    ...(safeActions.length > 0 ? { availableActions: safeActions } : {}),
    ...(isoOrNull(task.updatedAt) ? { updatedAt: isoOrNull(task.updatedAt)! } : {}),
  };
}

const STEP_LABELS: Record<ElyanTaskTraceStepId, string> = {
  intent: "İstek analizi",
  route: "Yönlendirme",
  plan: "Plan",
  delivery: "Masaüstü teslimatı",
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

function safeRuntimeDate(value: unknown): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

function runtimeExecutionTraceBlock(input: {
  task: TaskTraceSource;
  fallback: ElyanTaskTraceBlock;
}): ElyanTaskTraceBlock | null {
  const result = readRecord(input.task.result);
  const executionTrace = readRecord(result?.executionTrace);
  const rawSteps = Array.isArray(executionTrace?.steps)
    ? executionTrace.steps
    : Array.isArray(executionTrace?.stepStates)
      ? executionTrace.stepStates
      : [];
  if (rawSteps.length === 0) return null;

  const validId = /^[a-zA-Z0-9_-]{1,80}$/;
  const seen = new Set<string>();
  const steps = rawSteps.flatMap((value, index): ElyanTaskTraceStep[] => {
    const step = readRecord(value);
    if (!step) return [];
    const candidateId = readString(step, "id") ?? `step_${index + 1}`;
    const id = validId.test(candidateId) && !seen.has(candidateId)
      ? candidateId
      : `step_${index + 1}`;
    if (seen.has(id)) return [];
    seen.add(id);
    const rawStatus = readString(step, "status")?.toLowerCase();
    const status: ElyanTaskTraceStepStatus = rawStatus === "completed"
      ? "completed"
      : rawStatus === "failed"
        ? "failed"
        : rawStatus === "waiting_approval"
          ? "waiting_approval"
          : rawStatus === "skipped" || rawStatus === "canceled"
            ? "skipped"
            : rawStatus === "running"
              ? "running"
              : "pending";
    const capability = compactDetail(readString(step, "capability"), 120);
    const label = compactDetail(readString(step, "label"), 120)
      ?? (capability ? appLabelForTool(capability) : `Adım ${index + 1}`);
    const verificationStatus = readString(step, "verificationStatus");
    const attemptCount = Math.max(1, Math.min(32, Math.trunc(readNumber(step, "attemptCount") ?? 1)));
    const startedAt = safeRuntimeDate(step.startedAt);
    const completedAt = safeRuntimeDate(step.completedAt ?? step.finishedAt);
    const durationMs = readNumber(step, "durationMs");
    return [{
      id,
      label,
      status,
      ...(compactDetail(readString(step, "detail"), 240) ? {
        detail: compactDetail(readString(step, "detail"), 240),
      } : {}),
      ...(compactDetail(readString(step, "resultSummary"), 240) ? {
        resultSummary: compactDetail(readString(step, "resultSummary"), 240),
      } : {}),
      ...(capability ? { capability } : {}),
      ...(["pending", "passed", "repaired", "failed"].includes(verificationStatus ?? "")
        ? { verificationStatus: verificationStatus as "pending" | "passed" | "repaired" | "failed" }
        : {}),
      ...(attemptCount > 1 ? { attemptCount } : {}),
      ...(startedAt ? { startedAt } : {}),
      ...(completedAt ? { completedAt } : {}),
      ...(durationMs != null && durationMs >= 0 ? { durationMs } : {}),
    }];
  }).slice(0, 16);
  if (steps.length === 0) return null;

  const requestedActiveStepId = readString(executionTrace, "activeStepId");
  const activeStep = steps.find((step) => step.id === requestedActiveStepId)
    ?? steps.find((step) => step.status === "running" || step.status === "waiting_approval")
    ?? steps.find((step) => step.status === "pending");
  const verification = readRecord(executionTrace?.verification);
  const verificationStatus = readString(verification, "status");
  const stopReason = compactDetail(readString(executionTrace, "stopReason"), 160);
  const repairAttempts = Math.max(
    0,
    Math.min(32, Math.trunc(readNumber(executionTrace, "repairAttempts") ?? 0)),
  );

  return {
    ...input.fallback,
    title: compactDetail(readString(executionTrace, "title"), 120)
      ?? input.fallback.title,
    phase: activeStep?.id ?? input.fallback.phase,
    progressLabel: activeStep?.label ?? input.fallback.progressLabel,
    ...(activeStep ? { activeStepId: activeStep.id } : { activeStepId: undefined }),
    ...(["pending", "passed", "repaired", "failed"].includes(verificationStatus ?? "")
      ? { verification: { status: verificationStatus } as ElyanTaskTraceBlock["verification"] }
      : {}),
    ...(repairAttempts > 0 ? { repairAttempts } : {}),
    ...(stopReason ? { stopReason } : {}),
    steps,
  };
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

type DesktopPlanPreparationStatus = "pending" | "ready" | "failed";

function desktopPlanPreparationStatus(
  task: TaskTraceSource,
): DesktopPlanPreparationStatus | null {
  const payload = readRecord(task.payload);
  const workOrder = readRecord(payload?.desktopWorkOrder);
  const planPreview = readRecord(workOrder?.planPreview);
  const preparation = readRecord(planPreview?.planPreparation);
  const status = readString(preparation, "status")?.toLowerCase();

  if (status === "pending" || status === "ready" || status === "failed") {
    return status;
  }

  // Eski görevlerde hazırlık durumu ayrı alanda yoktur. Heuristic kaynak,
  // planın henüz desktop'a çalıştırılabilir olmadığını ifade eder.
  return readString(planPreview, "planSource")?.toLowerCase() === "heuristic"
    ? "pending"
    : null;
}

function describePlan(
  task: TaskTraceSource,
  routeDecision: ReturnType<typeof extractTaskRouteDecision>,
): string | undefined {
  const preparationStatus = desktopPlanPreparationStatus(task);
  if (preparationStatus === "pending") {
    return "Plan hazırlanıyor; masaüstü yürütmesi beklemede.";
  }
  if (preparationStatus === "failed") {
    return "Plan hazırlanamadı.";
  }

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

function hasDesktopWorkOrderEvidence(task: TaskTraceSource): boolean {
  const payload = readRecord(task.payload);
  const workOrder = readRecord(payload?.desktopWorkOrder);
  if (!workOrder) return false;
  const requiredCapabilities = Array.isArray(workOrder.requiredCapabilities)
    ? workOrder.requiredCapabilities.filter(
        (capability) =>
          typeof capability === "string" && capability.trim().length > 0,
      )
    : [];
  const planPreview = readRecord(workOrder.planPreview);
  const plannedSteps = Array.isArray(planPreview?.steps)
    ? planPreview.steps.length
    : 0;
  return requiredCapabilities.length > 0 || plannedSteps > 0;
}

function routeReasonIsInformative(input: {
  task: TaskTraceSource;
  routeDecision: ReturnType<typeof extractTaskRouteDecision>;
  toolNeeded: boolean;
}): boolean {
  const route =
    input.routeDecision?.taskRoute?.operationalRoute ??
    input.routeDecision?.route;
  if (input.routeDecision?.route === "pairing_required") {
    return true;
  }
  if (route === "desktop_runtime") {
    const executionPlan = input.routeDecision?.taskRoute?.executionPlan ?? [];
    const requiredCapabilities =
      input.routeDecision?.taskRoute?.requiredCapabilities ?? [];
    return (
      input.routeDecision?.taskRoute?.needsDesktop === true ||
      input.task.dispatchLeaseIssuedAt != null ||
      input.task.dispatchAckAt != null ||
      input.task.runtimeConnectionId != null ||
      input.task.status === "waiting_approval" ||
      input.task.status === "running" ||
      executionPlan.length > 0 ||
      requiredCapabilities.length > 0 ||
      hasDesktopWorkOrderEvidence(input.task)
    );
  }
  return input.toolNeeded && route !== "server_brain";
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
    normalizedError.includes("dispatch") ||
    normalizedError.includes("lease") ||
    normalizedError.includes("offline") ||
    normalizedError.includes("connection")
  ) {
    return "delivery";
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
    case "delivery":
      return "Masaüstüne aktarıyor";
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
    case "delivery":
      return "Masaüstü teslimatı doğrulanıyor.";
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

/**
 * ONAY KARTI SÖZLEŞMESİ: blok "onay bekliyor" diyorsa BİR ADIM da öyle demeli.
 *
 * Mobil, onay düğmelerini (`Onayla` / `Reddet`) blok durumundan DEĞİL adım
 * durumundan türetir: `needsApproval = steps.contains { $0.state ==
 * .waitingApproval }`. Sunucu tarafında hiçbir yol jenerik boru-hattı
 * adımlarından birini `waiting_approval` yapmıyordu — `advanceTaskTraceApproval`
 * adımları ARAÇ ADIYLA eşleştiriyor ve `intent/route/plan/.../response`
 * adımlarının hiçbirinde araç adı yok.
 *
 * Canlı sonuç (2026-08-21, görev 45dd0087): görev `waiting_approval`,
 * `approval_request` eksiksiz (Onayla/Reddet etiketleri, son kullanma dâhil),
 * ama telefonda düğme HİÇ çıkmadı; kullanıcı bastığını sandı, backend'e 90
 * dakika boyunca tek bir `/approval` isteği gelmedi ve görev 9 dakika sonra
 * iptal oldu.
 *
 * Bu kapı tek yerdedir: blok hangi yoldan üretilirse üretilsin (runtime izi ya
 * da fallback) mobilin sözleşmesi burada garanti edilir.
 */
/**
 * ADIM BAŞLIĞI YETENEK KİMLİĞİ OLAMAZ.
 *
 * Canlı ekran (2026-08-22): telefonda adım satırı "document_write — ." diye
 * göründü. İki ayrı kusur:
 *   - başlık ham yetenek kimliği (mobil, etiket yoksa `capability` alanına
 *     düşüyor — `DispatchStep.init`),
 *   - cümle yalnız noktadan ibaret (mobil tarafta ayrıca düzeltildi).
 *
 * Trace yolundaki adımların Türkçe etiketleri zaten var (`STEP_LABELS`), ama
 * plan/runtime yolundan gelen adımlar yetenek kimliğiyle geliyor. Manifest
 * `displayName` taşıyor; kullanan yoktu.
 */
function capabilityDisplayName(capability: string): string | null {
  const entry = DESKTOP_CAPABILITY_MANIFEST.find(
    (candidate) => candidate.name === capability,
  );
  const displayName = typeof entry?.displayName === "string" ? entry.displayName.trim() : "";
  return displayName.length > 0 ? displayName : null;
}

export function withCapabilityStepLabels(
  block: ElyanTaskTraceBlock,
): ElyanTaskTraceBlock {
  const steps = block.steps ?? [];
  if (steps.length === 0) return block;
  let changed = false;
  const labelled = steps.map((step) => {
    const capability =
      typeof (step as { capability?: unknown }).capability === "string"
        ? ((step as { capability?: string }).capability ?? "")
        : "";
    if (!capability) return step;
    const label = typeof step.label === "string" ? step.label.trim() : "";
    // Etiket yoksa ya da etiket yetenek kimliğinin ta kendisiyse düzelt.
    if (label.length > 0 && label !== capability) return step;
    const displayName = capabilityDisplayName(capability);
    if (!displayName) return step;
    changed = true;
    return { ...step, label: displayName };
  });
  return changed ? { ...block, steps: labelled } : block;
}

function ensureWaitingApprovalStep(
  block: ElyanTaskTraceBlock,
): ElyanTaskTraceBlock {
  if (block.status !== "waiting_approval") return block;
  const steps = block.steps ?? [];
  if (steps.length === 0) return block;
  if (steps.some((step) => step.status === "waiting_approval")) {
    // Adım zaten doğru; açık alanı da yaz ki mobil türetmeye mahkûm kalmasın.
    return block.needsApproval === true ? block : { ...block, needsApproval: true };
  }
  // Onayı hangi adım bekliyor: aktif adım → araç akışı → tamamlanmamış ilk
  // adım → son adım. Tamamlanmış bir adımı geri almaktansa gerçekten bekleyen
  // adımı işaretlemek doğrudur.
  const candidateId =
    steps.find((step) => step.id === block.activeStepId)?.id ??
    steps.find((step) => step.id === "tool")?.id ??
    steps.find(
      (step) => step.status !== "completed" && step.status !== "skipped",
    )?.id ??
    steps[steps.length - 1]?.id;
  if (!candidateId) return block;
  return {
    ...block,
    needsApproval: true,
    activeStepId: candidateId,
    steps: steps.map((step) =>
      step.id === candidateId
        ? {
            ...step,
            status: "waiting_approval" as const,
            detail: compactDetail(step.detail ?? block.summary ?? undefined)
              ?? "Onayını bekliyor.",
          }
        : step,
    ),
  };
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
  const planPreparationStatus = desktopPlanPreparationStatus(input.task);
  const planDetail = describePlan(input.task, routeDecision);
  const planReady =
    planPreparationStatus === "ready" ||
    (planPreparationStatus === null &&
      ((routeDecision?.taskRoute?.executionPlan?.length ?? 0) > 0 ||
        Boolean(routeDecision?.selectedWorkload)));
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
  const desktopTargeted =
    routeDecision?.taskRoute?.operationalRoute === "desktop_runtime" ||
    routeDecision?.route === "desktop_runtime";
  const desktopDeliveryComplete =
    desktopTargeted &&
    (input.task.dispatchAckAt != null ||
      input.task.status === "running" ||
      input.task.status === "completed" ||
      (input.task.status === "waiting_approval" &&
        input.task.runtimeConnectionId != null));
  const desktopDeliveryReady = !desktopTargeted || desktopDeliveryComplete;

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
            : planReady
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
        planReady ? input.task.updatedAt : null,
    }),
    buildStep({
      id: "delivery",
      status: !desktopTargeted
        ? "skipped"
        : failureStep === "delivery"
          ? "failed"
          : desktopDeliveryComplete
            ? "completed"
            : input.task.status === "waiting_approval"
              ? "pending"
              : "running",
      detail: !desktopTargeted
        ? undefined
        : failureStep === "delivery"
          ? compactDetail(input.task.error)
          : desktopDeliveryComplete
            ? "Masaüstü görevi aldı."
            : input.task.status === "waiting_approval"
              ? "Onaydan sonra masaüstüne aktarılacak."
              : input.task.dispatchLeaseIssuedAt != null
                ? "Masaüstü teslimatı doğrulanıyor."
                : "Masaüstü teslimatı hazırlanıyor.",
      task: input.task,
      startedAt: input.task.dispatchLeaseIssuedAt ?? input.task.updatedAt,
      completedAt:
        input.task.dispatchAckAt ??
        (desktopDeliveryComplete ? input.task.updatedAt : null),
    }),
    buildStep({
      id: "context",
      status:
        failureStep === "context"
          ? "failed"
          : context.needed && context.completed
            ? "completed"
            : context.needed &&
                traceStatus === "running" &&
                desktopDeliveryReady
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
            : tool.needed &&
                traceStatus === "running" &&
                desktopDeliveryReady
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
              ? // ARIZA ADIMI TEKTİR. Eskiden görev başarısız olduğunda bu
                // adım da körlemesine "failed" işaretleniyordu; mobil ilk
                // failed adımı gösterdiği için, arıza gerçekte `response`
                // adımında olsa bile ekranda hep "Kontrol adımında durdu"
                // yazıyordu — kullanıcıyı yanlış katmana bakmaya yönlendiren
                // bir yalan. Gerçek arıza adımını `resolveFailureStep` seçer;
                // ondan önceki adımlar atlanmıştır, sonrakiler hiç başlamadı.
                "skipped"
              : (traceStatus === "running" ||
                  traceStatus === "waiting_approval") &&
                desktopDeliveryReady
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
                ? // Tek arıza adımı kuralı (bkz. verify): arıza başka bir
                  // adımdaysa yanıt adımı hiç başlamamıştır.
                  "skipped"
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
  const visibleRouteReason =
    routeReason &&
    routeReasonIsInformative({
      task: input.task,
      routeDecision,
      toolNeeded: tool.needed,
    })
      ? routeReason
      : undefined;

  const fallback: ElyanTaskTraceBlock = {
    type: "dispatch_widget",
    stableBlockId: `dispatch_widget_${input.task.id}`,
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
    ...(visibleRouteReason ? { routeReason: visibleRouteReason } : {}),
    ...(activeStep ? { activeStepId: activeStep.id } : {}),
    steps,
  };
  return decorateLifecycleFields(
    withCapabilityStepLabels(
      ensureWaitingApprovalStep(
        runtimeExecutionTraceBlock({ task: input.task, fallback }) ?? fallback,
      ),
    ),
    input.task,
  );
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
    if (!isDispatchWidgetType(block?.type) || !Array.isArray(block?.steps)) return value;
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
