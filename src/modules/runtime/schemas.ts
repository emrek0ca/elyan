import { z } from "zod";
import { artifactInputSchema, taskStatusSchema } from "../../contracts/domain.js";

export const registerRuntimeBodySchema = z.object({
  deviceId: z.string().uuid(),
  deviceSecret: z.string().min(16),
  runtimeVersion: z.string().min(1).max(80).optional(),
  capabilities: z.array(z.string().min(1).max(80)).default([]),
});

export const runtimeHeartbeatBodySchema = z.object({
  status: z.enum(["online", "busy", "idle"]).default("online"),
  currentTaskId: z.string().uuid().optional(),
});

export const runtimeTaskParamsSchema = z.object({
  taskId: z.string().uuid(),
});

export const runtimeTaskUpdateBodySchema = z.object({
  status: taskStatusSchema,
  message: z.string().max(500).optional(),
  summary: z.string().optional(),
  error: z.string().optional(),
  approvalRequest: z.record(z.any()).optional(),
  result: z.record(z.any()).optional(),
  artifacts: z.array(artifactInputSchema).default([]),
});

export const runtimeSocketMessageSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("heartbeat"),
    status: z.enum(["online", "busy", "idle"]).default("online"),
    currentTaskId: z.string().uuid().optional(),
  }),
  z.object({
    type: z.literal("task.update"),
    taskId: z.string().uuid(),
    body: runtimeTaskUpdateBodySchema,
  }),
  z.object({
    type: z.literal("task.artifacts"),
    taskId: z.string().uuid(),
    artifacts: z.array(artifactInputSchema).min(1),
  }),
]);
