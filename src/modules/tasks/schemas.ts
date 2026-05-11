import { z } from "zod";
import { aiProviderSchema } from "../../contracts/domain.js";

export const createTaskBodySchema = z.object({
  targetDeviceId: z.string().uuid(),
  title: z.string().min(1).max(200),
  payload: z.record(z.any()),
  requestedCapabilities: z.array(z.string().min(1).max(80)).default([]),
  preferredAiProvider: aiProviderSchema.optional(),
});

export const taskParamsSchema = z.object({
  taskId: z.string().uuid(),
});

export const listTasksQuerySchema = z.object({
  targetDeviceId: z.string().uuid().optional(),
  status: z.string().optional(),
  limit: z.coerce.number().int().positive().max(100).default(50),
});

export const approvalBodySchema = z.object({
  approved: z.boolean(),
  notes: z.string().max(500).optional(),
});
