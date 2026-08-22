import { z } from "zod";

export const automationIntervalMinutesValues = [15, 60, 360, 720, 1440, 10080] as const;

const automationIntervalMinutesSchema = z.union(
  automationIntervalMinutesValues.map((value) => z.literal(value)) as [
    z.ZodLiteral<(typeof automationIntervalMinutesValues)[number]>,
    z.ZodLiteral<(typeof automationIntervalMinutesValues)[number]>,
    ...z.ZodLiteral<(typeof automationIntervalMinutesValues)[number]>[],
  ],
);

export const createAutomationBodySchema = z.object({
  sourceTaskId: z.string().uuid(),
  title: z.string().trim().min(1).max(200).optional(),
  intervalMinutes: automationIntervalMinutesSchema,
  timezone: z.string().trim().min(1).max(80).default("Europe/Istanbul"),
  firstRunAt: z.string().datetime().optional(),
  targetDeviceId: z.string().uuid().optional(),
});

export const updateAutomationBodySchema = z.object({
  status: z.enum(["active", "paused"]),
});

export const automationParamsSchema = z.object({
  automationId: z.string().uuid(),
});

export const listAutomationsQuerySchema = z.object({
  limit: z.coerce.number().int().positive().max(100).default(50),
});
