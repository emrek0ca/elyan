import { z } from "zod";
import {
  sessionGoalScheduleHintValues,
  sessionGoalStatusValues,
} from "../../contracts/domain.js";

export const goalParamsSchema = z.object({
  goalId: z.string().uuid(),
});

export const createGoalBodySchema = z.object({
  sessionId: z.string().uuid().optional(),
  taskId: z.string().uuid().optional(),
  title: z.string().min(1).max(200),
  description: z.string().max(4_000).optional(),
  maxSteps: z.number().int().min(1).max(20).optional(),
  scheduleHint: z.enum(sessionGoalScheduleHintValues).nullable().optional(),
  dueAt: z.string().datetime().nullable().optional(),
});

export const listGoalsQuerySchema = z.object({
  status: z.enum(sessionGoalStatusValues).optional(),
  sessionId: z.string().uuid().optional(),
  limit: z.coerce.number().int().min(1).max(50).default(20),
});

export const updateGoalBodySchema = z.object({
  status: z.enum(sessionGoalStatusValues).optional(),
  title: z.string().min(1).max(200).optional(),
  description: z.string().max(4_000).optional(),
  scheduleHint: z.enum(sessionGoalScheduleHintValues).nullable().optional(),
  dueAt: z.string().datetime().nullable().optional(),
});

export const advanceGoalBodySchema = z.object({
  step: z.number().int().min(0).max(20),
  ofSteps: z.number().int().min(1).max(20),
  advancedTo: z.string().min(1).max(400),
  blocker: z.string().min(1).max(400).nullable().optional(),
  done: z.boolean().optional(),
});
