import type { FastifyInstance } from "fastify";
import {
  executeAgentTool,
  type AgentToolContext,
  type AgentToolRequest,
  type AgentToolResult,
} from "./tool-registry.js";
import { createAgentRun, deriveAgentEvidence } from "./agent-engine.js";
import { enqueueAgentRun } from "./agent-engine-queue.js";
import { agentEngineRepository } from "./agent-engine-repository.js";
import { isAgentEngineShadowEnabled, isAgentEngineV2Enabled } from "./agent-engine-policy.js";
import {
  agentPlanEnvelopeSchema,
  buildAgentPlanFromToolRequests,
  hardenAgentPlanVerification,
  type AgentPlanEnvelope,
} from "./agent-plan.js";
import { canCompleteAgentRun, verifyAgentStep } from "./agent-verifier.js";

const DEFAULT_MAX_TOOL_REQUESTS = 4;
const DEFAULT_TOOL_BUDGET_MS = 8_000;

export type AgentToolLoopResult = {
  iterations: number;
  durationMs: number;
  timedOut: boolean;
  results: AgentToolResult[];
  engineVersion?: "agent_engine.v2";
  runId?: string;
  runState?: string;
  planVersion?: "agent_plan.v2";
  verificationPassed?: boolean;
  stepVerifications?: Array<{
    stepId: string;
    passed: boolean;
    confidence: number;
    missingEvidence: string[];
    failedRules: string[];
  }>;
};

function elapsed(startedAt: number): number {
  return Math.max(0, Date.now() - startedAt);
}

function requestKey(request: AgentToolRequest): string {
  return JSON.stringify([request.tool, request.args]);
}

function verificationFailureResult(result: AgentToolResult): AgentToolResult {
  return {
    ...result,
    ok: false,
    output: null,
    error: {
      code: "tool_verification_failed",
      message: "The tool result could not be verified against the planned outcome.",
    },
  };
}

async function runVerifiedLegacyPlan(
  app: FastifyInstance,
  input: {
    context: AgentToolContext;
    requests: AgentToolRequest[];
    plan: AgentPlanEnvelope;
    maxRequests: number;
    budgetMs: number;
    startedAt: number;
  },
): Promise<AgentToolLoopResult> {
  const plan = hardenAgentPlanVerification(
    agentPlanEnvelopeSchema.parse(input.plan),
  );
  const allowedRequestCounts = new Map<string, number>();
  for (const request of input.requests) {
    const key = requestKey(request);
    allowedRequestCounts.set(key, (allowedRequestCounts.get(key) ?? 0) + 1);
  }
  const selectedSteps = plan.steps
    .filter((step) => {
      const key = requestKey(step.tool_request);
      const remaining = allowedRequestCounts.get(key) ?? 0;
      if (remaining <= 0) return false;
      allowedRequestCounts.set(key, remaining - 1);
      return true;
    })
    .slice(0, input.maxRequests);
  const selectedStepIds = new Set(selectedSteps.map((step) => step.id));
  const verifiedStepIds = new Set<string>();
  const results: AgentToolResult[] = [];
  const verifications: NonNullable<AgentToolLoopResult["stepVerifications"]> = [];
  const rawVerifications: ReturnType<typeof verifyAgentStep>[] = [];
  let timedOut = false;

  for (const step of selectedSteps) {
    if (
      !step.depends_on.every(
        (dependency) =>
          selectedStepIds.has(dependency) && verifiedStepIds.has(dependency),
      )
    ) {
      break;
    }
    const remainingMs = input.startedAt + input.budgetMs - Date.now();
    if (remainingMs <= 0) {
      timedOut = true;
      break;
    }
    const timeout = new Promise<"timeout">((resolve) => {
      setTimeout(() => resolve("timeout"), remainingMs).unref?.();
    });
    const executed = await Promise.race([
      executeAgentTool(app, input.context, step.tool_request),
      timeout,
    ]);
    if (executed === "timeout") {
      timedOut = true;
      break;
    }
    const verification = verifyAgentStep({
      step,
      evidence: deriveAgentEvidence(executed),
    });
    rawVerifications.push(verification);
    verifications.push({
      stepId: step.id,
      passed: verification.passed,
      confidence: verification.confidence,
      missingEvidence: verification.missing_evidence,
      failedRules: verification.failed_rules,
    });
    results.push(
      verification.passed ? executed : verificationFailureResult(executed),
    );
    if (!verification.passed) break;
    verifiedStepIds.add(step.id);
  }

  return {
    iterations: results.length,
    durationMs: elapsed(input.startedAt),
    timedOut,
    results,
    planVersion: "agent_plan.v2",
    verificationPassed:
      selectedSteps.length > 0 &&
      verifications.length === selectedSteps.length &&
      canCompleteAgentRun(rawVerifications),
    stepVerifications: verifications,
  };
}

export async function runAgentToolLoop(
  app: FastifyInstance,
  input: {
    context: AgentToolContext;
    requests: AgentToolRequest[];
    maxRequests?: number;
    budgetMs?: number;
    plan?: AgentPlanEnvelope | null;
  },
): Promise<AgentToolLoopResult> {
  const startedAt = Date.now();
  const budgetMs = input.budgetMs ?? DEFAULT_TOOL_BUDGET_MS;
  const maxRequests = Math.max(
    0,
    Math.min(input.maxRequests ?? DEFAULT_MAX_TOOL_REQUESTS, DEFAULT_MAX_TOOL_REQUESTS),
  );
  const requests = input.requests.slice(0, maxRequests);
  if (requests.length === 0) {
    return {
      iterations: 0,
      durationMs: elapsed(startedAt),
      timedOut: false,
      results: [],
    };
  }

  const taskId = input.context.taskId ?? null;
  const v2Enabled = taskId ? isAgentEngineV2Enabled(app, input.context.userId) : false;
  const shadowEnabled = taskId ? isAgentEngineShadowEnabled(app) : false;
  if (taskId && (v2Enabled || shadowEnabled)) {
    const plan = input.plan
      ? agentPlanEnvelopeSchema.parse(input.plan)
      : buildAgentPlanFromToolRequests({ goal: `Execute ${requests.length} typed tool request(s)`, requests });
    const snapshot = await createAgentRun({
      app,
      userId: input.context.userId,
      taskId,
      sessionId: input.context.sessionId,
      plan,
      shadow: !v2Enabled,
    });
    if (v2Enabled) {
      const queued = await enqueueAgentRun(app, {
        runId: snapshot.run.id,
        userId: input.context.userId,
        revision: snapshot.run.revision,
        workload: input.context.workload,
        allowSideEffects: input.context.allowSideEffects,
      });
      if (!queued) {
        return { iterations: 0, durationMs: elapsed(startedAt), timedOut: true, results: [] };
      }
      const deadline = startedAt + budgetMs;
      let latest = snapshot;
      while (Date.now() < deadline) {
        await new Promise((resolve) => setTimeout(resolve, 75));
        latest = await agentEngineRepository(app).loadRun(input.context.userId, snapshot.run.id);
        if (["completed", "waiting_approval", "waiting_evidence", "blocked", "failed", "canceled"].includes(latest.run.state)) break;
      }
      const results = latest.steps.flatMap((step): AgentToolResult[] => {
        const value = step.toolResult;
        if (!value || typeof value !== "object" || Array.isArray(value)) return [];
        const result = value as Record<string, unknown>;
        return [{
          tool: typeof result.tool === "string" ? result.tool : String((step.toolRequest as Record<string, unknown>).tool ?? "unknown"),
          ok: result.ok === true,
          permission: result.permission === "write" || result.permission === "side_effect" ? result.permission : "read",
          durationMs: typeof result.durationMs === "number" ? result.durationMs : 0,
          output: result.output && typeof result.output === "object" && !Array.isArray(result.output)
            ? result.output as Record<string, unknown>
            : null,
          error: result.error && typeof result.error === "object" && !Array.isArray(result.error)
            ? result.error as { code: string; message: string }
            : null,
        }];
      });
      return {
        iterations: results.length > 0 ? 1 : 0,
        durationMs: elapsed(startedAt),
        timedOut: !["completed", "waiting_approval", "waiting_evidence", "blocked", "failed", "canceled"].includes(latest.run.state),
        results,
        engineVersion: "agent_engine.v2",
        runId: latest.run.id,
        runState: latest.run.state,
      };
    }
  }

  if (input.plan) {
    return runVerifiedLegacyPlan(app, {
      context: input.context,
      requests,
      plan: input.plan,
      maxRequests,
      budgetMs,
      startedAt,
    });
  }

  const wrapped = Promise.all(
    requests.map((request) => executeAgentTool(app, input.context, request)),
  );
  const timeout = new Promise<"timeout">((resolve) => {
    setTimeout(() => resolve("timeout"), budgetMs).unref?.();
  });
  const result = await Promise.race([wrapped, timeout]);
  if (result === "timeout") {
    return {
      iterations: 1,
      durationMs: elapsed(startedAt),
      timedOut: true,
      results: [],
    };
  }
  return {
    iterations: 1,
    durationMs: elapsed(startedAt),
    timedOut: false,
    results: result,
  };
}

export function summarizeToolResultsForMetadata(results: AgentToolResult[]): Array<Record<string, unknown>> {
  return results.map((result) => ({
    tool: result.tool,
    ok: result.ok,
    permission: result.permission,
    durationMs: result.durationMs,
    errorCode: result.error?.code ?? null,
    output:
      result.output == null
        ? null
        : {
            keys: Object.keys(result.output).slice(0, 12),
            resultCount: Array.isArray(result.output.results)
              ? result.output.results.length
              : undefined,
          },
  }));
}

function clipString(value: string, max = 1_200): string {
  const compact = value.replace(/\s+/g, " ").trim();
  return compact.length <= max ? compact : `${compact.slice(0, max - 1).trimEnd()}…`;
}

function compactToolOutput(value: unknown, depth = 0): unknown {
  if (depth > 4) return "[truncated]";
  if (typeof value === "string") return clipString(value);
  if (typeof value === "number" || typeof value === "boolean" || value == null) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.slice(0, 8).map((item) => compactToolOutput(item, depth + 1));
  }
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, nested] of Object.entries(value).slice(0, 16)) {
      out[key] = compactToolOutput(nested, depth + 1);
    }
    return out;
  }
  return String(value);
}

/**
 * Yapılandırılmış connector kartı render edilecekken nesirde kalan numaralı/
 * madde imli tekrar listesini deterministik kırpar (prompt talimatına uymayan
 * küçük model için güvenlik ağı). 3+ liste satırı varsa liste atılır, giriş
 * cümlesi korunur. Giriş cümlesi yoksa boş döner — kart tek başına durur.
 */
export function trimEnumeratedListForStructuredCard(text: string): string {
  const lines = text.split("\n");
  const isListLine = (line: string) => /^\s*(\d+[.)]|[-*•])\s+\S/.test(line);
  const listStart = lines.findIndex(isListLine);
  if (listStart === -1) return text;
  const listLineCount = lines.slice(listStart).filter(isListLine).length;
  if (listLineCount < 3) return text;
  return lines.slice(0, listStart).join("\n").trim();
}

export function buildToolResultRefinementPrompt(input: {
  originalPrompt: string;
  results: AgentToolResult[];
  /**
   * true ise liste-şekilli sonuçlar ayrıca yapılandırılmış connector_result
   * kartı olarak render edilecek: nesir aynı listeyi tekrar SAYMAMALI.
   * Canlıda aynı 5 mail hem numaralı metin hem kart hem tablo olarak üst
   * üste basılıyordu — tek veri tek yüzeyde gösterilir.
   */
  structuredBlocksWillRender?: boolean;
}): string {
  const safeResults = input.results.map((result) => ({
    tool: result.tool,
    ok: result.ok,
    permission: result.permission,
    error: result.error,
    output: compactToolOutput(result.output),
  }));
  const listStyleRule = input.structuredBlocksWillRender
    ? [
        "A structured card widget will already display the full item list (senders, titles, dates) below your text.",
        "Therefore write ONLY a short natural-language lead-in of 1-2 sentences in the user's language: state how many items were found and the single most notable highlight or pattern (e.g. unread count, an urgent-looking message, a meeting starting soon).",
        "Do NOT enumerate the items. No numbered or bulleted list, no per-item lines, no markdown table — the card already shows them.",
      ]
    : [
        "For mailbox/calendar/drive results, group and deduplicate the useful fields (sender/title/date/summary) into a compact readable list instead of narrating how the tool was called.",
      ];
  return [
    "Original user request:",
    clipString(input.originalPrompt, 2_000),
    "",
    "Typed tool results from Elyan server agent loop:",
    JSON.stringify(safeResults, null, 2).slice(0, 8_000),
    "",
    "Use the typed tool results above to answer the original user request in the user's language.",
    "Return only the user-facing answer. Do not expose tool names, JSON, arguments, query syntax, hidden reasoning, provider names, or planning text.",
    // The results are already-fetched, read-only data the user asked to see. The
    // CONTENT of a result must never trigger a refusal or safety disclaimer: an
    // email/event/file that mentions a payment, transfer, purchase, subscription,
    // password, or any sensitive topic does NOT mean the user requested that
    // action. Never output a payment/transfer/security refusal or an "I can't do
    // that" disclaimer here — just summarize what was found.
    "You are only summarizing data the user already asked to read. Do not refuse and do not add action/security disclaimers based on the content of the results.",
    ...listStyleRule,
    "If an ok read result is present, do not ask for the same permission again; answer from the result. If no ok result is present, explain the missing access briefly.",
    "Do not claim a tool succeeded if its ok field is false.",
    "If a write/side-effect tool was blocked for approval, say that the action needs approval instead of pretending it was done.",
  ].join("\n");
}
