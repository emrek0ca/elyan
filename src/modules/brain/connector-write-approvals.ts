import { randomUUID } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import {
  getAgentToolMetadata,
  readCanonicalAgentToolArgs,
  type AgentToolRequest,
} from "./tool-registry.js";
import {
  connectorToolContract,
  describeConnectorWriteDraft,
  type ConnectorWriteDraft,
} from "./connector-tools.js";
import type { SharedBrainWorkload } from "./workloads.js";

const STAGE_TTL_MS = 10 * 60 * 1_000;

export type DurableConnectorWriteApproval = {
  remainingApprovals?: DurableConnectorWriteApproval[];
  kind: "connector_write";
  token: string;
  userId: string;
  taskId: string;
  sessionId: string | null;
  workload: SharedBrainWorkload;
  expiresAt: number;
  connectorCall: AgentToolRequest;
  draft: ConnectorWriteDraft;
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Bind the visible draft to the exact registered side-effect call. */
export function readCanonicalConnectorWriteApprovalCall(
  value: unknown,
): AgentToolRequest | null {
  const approval = asRecord(value);
  const call = asRecord(approval?.connectorCall);
  const tool = typeof call?.tool === "string" ? call.tool.trim() : "";
  const args = asRecord(call?.args);
  const contract = connectorToolContract(tool);
  const metadata = getAgentToolMetadata(tool);
  const canonicalArgs = readCanonicalAgentToolArgs(tool, args);
  if (
    approval?.kind !== "connector_write" ||
    !tool ||
    !args ||
    !canonicalArgs ||
    contract?.permission !== "side_effect" ||
    metadata?.permission !== "side_effect"
  ) {
    return null;
  }
  const canonicalDraft = describeConnectorWriteDraft(tool, canonicalArgs);
  if (!canonicalDraft || !isDeepStrictEqual(canonicalDraft, approval.draft)) {
    return null;
  }
  return { tool, args: canonicalArgs };
}

/**
 * Builds the durable approval payload that is persisted on the existing task
 * approvalRequest/blob contract. No process-local registry is used: the task id
 * is part of the opaque token and the random suffix prevents guessing.
 */
export function stageConnectorWriteApproval(input: {
  userId: string;
  taskId?: string | null;
  sessionId?: string | null;
  workload: SharedBrainWorkload;
  request: AgentToolRequest;
}): DurableConnectorWriteApproval | null {
  const taskId = input.taskId?.trim();
  if (!taskId) return null;
  const metadata = getAgentToolMetadata(input.request.tool);
  if (metadata?.permission !== "side_effect") return null;
  const canonicalArgs = readCanonicalAgentToolArgs(
    input.request.tool,
    input.request.args,
  );
  if (!canonicalArgs) return null;
  const draft = describeConnectorWriteDraft(
    input.request.tool,
    canonicalArgs,
  );
  if (!draft) return null;
  return {
    kind: "connector_write",
    token: `${taskId}.${randomUUID()}`,
    userId: input.userId,
    taskId,
    sessionId: input.sessionId ?? null,
    workload: input.workload,
    expiresAt: Date.now() + STAGE_TTL_MS,
    connectorCall: {
      tool: input.request.tool,
      args: canonicalArgs,
    },
    draft,
  };
}

export function connectorWriteTaskIdFromToken(token: string): string | null {
  const separator = token.indexOf(".");
  if (separator <= 0) return null;
  const taskId = token.slice(0, separator).trim();
  const nonce = token.slice(separator + 1).trim();
  return taskId && nonce ? taskId : null;
}
