import { randomUUID } from 'crypto';
import type { TeamRole } from '@/core/orchestration';
import { getTeamRoleDefinition } from './roles';
import { teamPlanSchema, type TeamAgent, type TeamPlan, type TeamPlannerInput, type TeamTask } from './types';

function createAgent(role: TeamRole, modelRoutingMode: TeamPlan['modelRoutingMode']): TeamAgent {
  const definition = getTeamRoleDefinition(role, modelRoutingMode);

  return {
    id: `agent_${definition.role}`,
    role: definition.role,
    title: definition.title,
    modelRoutingMode: definition.modelRoutingMode,
    permissions: definition.permissions,
    systemPrompt: definition.systemPrompt,
  };
}

function addTask(tasks: TeamTask[], task: Omit<TeamTask, 'status'>) {
  tasks.push({
    ...task,
    status: 'pending',
  });
}

function validateTaskGraph(tasks: TeamTask[]) {
  const taskIds = new Set(tasks.map((task) => task.id));

  for (const task of tasks) {
    for (const dependency of task.dependsOn) {
      if (!taskIds.has(dependency)) {
        throw new Error(`Team task ${task.id} depends on missing task ${dependency}.`);
      }
    }
  }

  const visiting = new Set<string>();
  const visited = new Set<string>();
  const byId = new Map(tasks.map((task) => [task.id, task]));

  function visit(taskId: string) {
    if (visited.has(taskId)) {
      return;
    }

    if (visiting.has(taskId)) {
      throw new Error(`Team task graph contains a cycle at ${taskId}.`);
    }

    visiting.add(taskId);
    for (const dependency of byId.get(taskId)?.dependsOn ?? []) {
      visit(dependency);
    }
    visiting.delete(taskId);
    visited.add(taskId);
  }

  for (const task of tasks) {
    visit(task.id);
  }
}

export function buildTeamPlan(input: TeamPlannerInput): TeamPlan {
  const sourcePolicy = input.sourcePlan.teamPolicy;
  const modelRoutingMode =
    input.sourcePlan.taskIntent === 'personal_workflow'
      ? 'local_only'
      : input.allowCloudEscalation
        ? input.sourcePlan.routingMode
        : sourcePolicy.modelRoutingMode;
  const roles = sourcePolicy.requiredRoles.length > 0 ? sourcePolicy.requiredRoles : (['planner', 'verifier'] as TeamRole[]);
  const agents = roles.map((role) => createAgent(role, modelRoutingMode));
  const tasks: TeamTask[] = [];

  addTask(tasks, {
    id: 'scope',
    title: 'Scope request',
    summary: 'Clarify the user goal, constraints, execution surface, and risks.',
    kind: 'analysis',
    assignedRole: 'planner',
    dependsOn: [],
    requiresConfirmation: false,
  });

  if (roles.includes('researcher')) {
    addTask(tasks, {
      id: 'research',
      title: 'Gather context',
      summary: 'Use retrieved sources and available context to separate facts from assumptions.',
      kind: 'research',
      assignedRole: 'researcher',
      dependsOn: ['scope'],
      requiresConfirmation: false,
    });
  }

  if (roles.includes('executor')) {
    addTask(tasks, {
      id: 'execute',
      title: 'Produce working answer',
      summary: 'Generate the concrete answer or implementation-oriented output within policy boundaries.',
      kind: 'execution',
      assignedRole: 'executor',
      dependsOn: roles.includes('researcher') ? ['research'] : ['scope'],
      requiresConfirmation: input.sourcePlan.executionPolicy.requiresConfirmation,
    });
  }

  if (roles.includes('reviewer')) {
    addTask(tasks, {
      id: 'review',
      title: 'Review output',
      summary: 'Check correctness, missing constraints, regressions, and unsupported claims.',
      kind: 'review',
      assignedRole: 'reviewer',
      dependsOn: tasks.some((task) => task.id === 'execute') ? ['execute'] : roles.includes('researcher') ? ['research'] : ['scope'],
      requiresConfirmation: false,
    });
  }

  if (roles.includes('memory_curator')) {
    addTask(tasks, {
      id: 'memory',
      title: 'Identify memory candidates',
      summary: 'Extract durable project or preference facts without storing secrets.',
      kind: 'memory',
      assignedRole: 'memory_curator',
      dependsOn: tasks.some((task) => task.id === 'review') ? ['review'] : tasks[tasks.length - 1]?.id ? [tasks[tasks.length - 1].id] : ['scope'],
      requiresConfirmation: false,
    });
  }

  addTask(tasks, {
    id: 'verify',
    title: 'Verify final answer',
    summary: 'Decide if the team output can be safely presented to the user.',
    kind: 'verification',
    assignedRole: 'verifier',
    dependsOn: tasks.length > 0 ? [tasks[tasks.length - 1].id] : ['scope'],
    requiresConfirmation: false,
  });

  if (tasks.length > input.maxTasksPerRun) {
    throw new Error(`Team plan has ${tasks.length} tasks, exceeding the configured limit of ${input.maxTasksPerRun}.`);
  }

  validateTaskGraph(tasks);

  return teamPlanSchema.parse({
    runId: `team_${randomUUID()}`,
    createdAt: new Date().toISOString(),
    query: input.query,
    mode: input.mode,
    requestedModelId: input.requestedModelId,
    modelRoutingMode,
    maxConcurrentAgents: input.maxConcurrentAgents,
    maxTasksPerRun: input.maxTasksPerRun,
    allowCloudEscalation: input.allowCloudEscalation,
    agents,
    tasks,
    policy: {
      reasons: sourcePolicy.reasons,
      riskBoundary: sourcePolicy.riskBoundary,
      sourcePlanTaskIntent: input.sourcePlan.taskIntent,
      sourcePlanMode: input.sourcePlan.mode,
    },
  });
}

export const __teamPlannerTestHooks = {
  validateTaskGraph,
};
