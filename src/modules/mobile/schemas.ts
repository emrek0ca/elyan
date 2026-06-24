import { z } from "zod";

export const worldSignalKindSchema = z.enum([
  "health",
  "location",
  "calendar",
  "time",
  "device",
  "notification",
  "camera",
  "speech",
  "attachment",
]);

export const uploadWorldSignalsBodySchema = z.object({
  schemaVersion: z.literal(1),
  clientRequestId: z.string().min(1).max(160),
  userId: z.string().min(1).max(160).optional(),
  deviceId: z.string().min(1).max(160),
  sessionId: z.string().uuid().optional().nullable(),
  signals: z
    .array(
      z.object({
        signalId: z.string().min(1).max(160),
        source: z.literal("mobile"),
        kind: worldSignalKindSchema,
        summary: z.string().min(1).max(480),
        confidence: z.number().finite().min(0).max(1),
        facts: z.record(z.string(), z.unknown()),
        privacy: z.record(z.string(), z.unknown()),
        renderHints: z.record(z.string(), z.unknown()).optional(),
        visibility: z
          .enum(["user_visible", "assistant_internal_by_default"])
          .optional(),
        createdAt: z.string().datetime(),
      }),
    )
    .min(1)
    .max(16),
});

export type UploadWorldSignalsBody = z.infer<typeof uploadWorldSignalsBodySchema>;
