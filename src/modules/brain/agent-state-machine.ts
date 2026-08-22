import type { AgentRunState, AgentStepState } from "./agent-plan.js";

const runTransitions: Record<AgentRunState, ReadonlySet<AgentRunState>> = {
  understanding: new Set(["planning", "canceled", "failed"]),
  planning: new Set(["ready", "blocked", "failed", "canceled"]),
  ready: new Set(["executing", "blocked", "canceled", "failed"]),
  executing: new Set(["observing", "waiting_approval", "replanning", "failed", "canceled"]),
  observing: new Set(["verifying", "replanning", "failed", "canceled"]),
  verifying: new Set(["ready", "completed", "waiting_evidence", "replanning", "blocked", "failed", "canceled"]),
  waiting_approval: new Set(["ready", "canceled", "blocked"]),
  waiting_evidence: new Set(["ready", "replanning", "blocked", "canceled"]),
  replanning: new Set(["ready", "blocked", "failed", "canceled"]),
  completed: new Set(), blocked: new Set(), failed: new Set(), canceled: new Set(),
};

const stepTransitions: Record<AgentStepState, ReadonlySet<AgentStepState>> = {
  pending: new Set(["ready", "skipped", "canceled"]),
  ready: new Set(["executing", "skipped", "canceled"]),
  executing: new Set(["observed", "waiting_approval", "failed", "canceled"]),
  observed: new Set(["verified", "waiting_evidence", "failed", "canceled"]),
  waiting_approval: new Set(["ready", "canceled"]),
  waiting_evidence: new Set(["ready", "failed", "skipped", "canceled"]),
  verified: new Set(), failed: new Set(["ready", "skipped", "canceled"]), skipped: new Set(), canceled: new Set(),
};

export function assertAgentRunTransition(from: AgentRunState, to: AgentRunState): void {
  if (from !== to && !runTransitions[from].has(to)) throw new Error(`invalid_agent_run_transition:${from}:${to}`);
}

export function assertAgentStepTransition(from: AgentStepState, to: AgentStepState): void {
  if (from !== to && !stepTransitions[from].has(to)) throw new Error(`invalid_agent_step_transition:${from}:${to}`);
}
