import type { FastifyInstance } from "fastify";
import {
  executeAgentTool,
  type AgentToolContext,
  type AgentToolRequest,
  type AgentToolResult,
} from "./tool-registry.js";

const DEFAULT_MAX_TOOL_REQUESTS = 4;
const DEFAULT_TOOL_BUDGET_MS = 8_000;

export type AgentToolLoopResult = {
  iterations: number;
  durationMs: number;
  timedOut: boolean;
  results: AgentToolResult[];
};

function elapsed(startedAt: number): number {
  return Math.max(0, Date.now() - startedAt);
}

export async function runAgentToolLoop(
  app: FastifyInstance,
  input: {
    context: AgentToolContext;
    requests: AgentToolRequest[];
    maxRequests?: number;
    budgetMs?: number;
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

export function buildToolResultRefinementPrompt(input: {
  originalPrompt: string;
  results: AgentToolResult[];
}): string {
  const safeResults = input.results.map((result) => ({
    tool: result.tool,
    ok: result.ok,
    permission: result.permission,
    error: result.error,
    output: compactToolOutput(result.output),
  }));
  return [
    "Original user request:",
    clipString(input.originalPrompt, 2_000),
    "",
    "Typed tool results from Elyan server agent loop:",
    JSON.stringify(safeResults, null, 2).slice(0, 8_000),
    "",
    "Use the typed tool results above to answer the original user request.",
    "Do not expose hidden reasoning. Do not claim a tool succeeded if its ok field is false.",
    "If a write/side-effect tool was blocked for approval, say that the action needs approval instead of pretending it was done.",
  ].join("\n");
}
