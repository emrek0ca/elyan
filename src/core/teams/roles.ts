import type { ModelRoutingMode, TeamRole } from '@/core/orchestration';
import type { TeamPermission, TeamRoleDefinition } from './types';

const BASE_BOUNDARY =
  'You are one bounded Elyan team agent. Do not spawn sub-agents. Do not claim side effects unless a typed capability result is present. Keep outputs concise, auditable, and usable by the verifier.';

const roleDefinitions: Record<TeamRole, TeamRoleDefinition> = {
  planner: {
    role: 'planner',
    title: 'Planner',
    permissions: ['read_context'],
    modelRoutingMode: 'local_first',
    systemPrompt: `${BASE_BOUNDARY} Convert the user request into crisp scope, risks, and task intent. Prefer stable architecture over flashy shortcuts.`,
  },
  researcher: {
    role: 'researcher',
    title: 'Researcher',
    permissions: ['read_context', 'use_retrieval', 'use_browser_read'],
    modelRoutingMode: 'local_first',
    systemPrompt: `${BASE_BOUNDARY} Extract relevant evidence from provided sources. Separate sourced facts from inference. Never invent citations.`,
  },
  executor: {
    role: 'executor',
    title: 'Executor',
    permissions: ['read_context', 'use_local_capability', 'use_mcp', 'request_action'],
    modelRoutingMode: 'local_first',
    systemPrompt: `${BASE_BOUNDARY} Produce the implementation-oriented answer or artifact. Respect policy gates and avoid unapproved destructive actions.`,
  },
  reviewer: {
    role: 'reviewer',
    title: 'Reviewer',
    permissions: ['read_context'],
    modelRoutingMode: 'local_first',
    systemPrompt: `${BASE_BOUNDARY} Review the draft for correctness, missing constraints, regression risk, and unsupported claims.`,
  },
  verifier: {
    role: 'verifier',
    title: 'Verifier',
    permissions: ['read_context'],
    modelRoutingMode: 'local_first',
    systemPrompt: `${BASE_BOUNDARY} Decide whether the team output is safe to present. Start with PASS or FAIL, then one short reason.`,
  },
  memory_curator: {
    role: 'memory_curator',
    title: 'Memory Curator',
    permissions: ['read_context', 'write_memory'],
    modelRoutingMode: 'local_only',
    systemPrompt: `${BASE_BOUNDARY} Identify durable, auditable memory candidates. Do not store secrets or transient chatter.`,
  },
};

export function getTeamRoleDefinition(role: TeamRole, routingMode: ModelRoutingMode): TeamRoleDefinition {
  const definition = roleDefinitions[role];
  const localRoutingMode: ModelRoutingMode =
    role === 'memory_curator' || routingMode === 'local_only' ? 'local_only' : routingMode;

  return {
    ...definition,
    permissions: [...definition.permissions] as TeamPermission[],
    modelRoutingMode: localRoutingMode,
  };
}
