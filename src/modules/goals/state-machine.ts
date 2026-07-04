import { z } from "zod";

export const goalEngineStateSchema = z.enum([
  "open", "planned", "executing", "waiting", "completed", "blocked",
]);
export type GoalEngineState = z.infer<typeof goalEngineStateSchema>;

const transitions: Record<GoalEngineState, ReadonlySet<GoalEngineState>> = {
  open: new Set(["planned", "executing", "waiting", "blocked", "completed"]),
  planned: new Set(["executing", "waiting", "blocked", "completed"]),
  executing: new Set(["waiting", "blocked", "completed"]),
  waiting: new Set(["executing", "blocked", "completed"]),
  blocked: new Set(["planned", "executing", "waiting", "completed"]),
  completed: new Set(),
};

export function assertGoalTransition(from: GoalEngineState, to: GoalEngineState): void {
  if (from === to) return;
  if (!transitions[from].has(to)) {
    throw new Error(`invalid_goal_transition:${from}:${to}`);
  }
}

export function readGoalEngineState(progress: unknown): GoalEngineState {
  if (progress && typeof progress === "object" && !Array.isArray(progress)) {
    const parsed = goalEngineStateSchema.safeParse((progress as Record<string, unknown>).engineState);
    if (parsed.success) return parsed.data;
  }
  return "open";
}

export function mergeGoalEngineState(progress: unknown, state: GoalEngineState): Record<string, unknown> {
  const base = progress && typeof progress === "object" && !Array.isArray(progress)
    ? progress as Record<string, unknown>
    : {};
  return { ...base, engineState: state };
}
