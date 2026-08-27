import { z } from "zod";
import { hasRawBinaryUploadHint } from "../../lib/derived-data.js";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";

const taskPayloadSchema = z
  .object({
    prompt: z.string().trim().min(1).max(20_000),
    source: z.enum(["mobile", "desktop"]).default("mobile"),
    metadata: boundedJsonRecordSchema.optional(),
  })
  .passthrough();

export const createTaskBodySchema = z
  .object({
    targetDeviceId: z.string().uuid().optional(),
    title: z.string().trim().min(1).max(200),
    payload: taskPayloadSchema,
    requestedCapabilities: z
      .array(z.string().trim().min(1).max(80))
      .max(20)
      .transform((values) => [...new Set(values)]),
  })
  .superRefine((input, ctx) => {
    if (hasRawBinaryUploadHint(input.payload)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["payload"],
        message:
          "raw binary upload payload is not accepted; send processed data only",
      });
    }

    if (hasRawBinaryUploadHint(input.payload?.metadata)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["payload", "metadata"],
        message:
          "raw binary upload payload is not accepted; send processed data only",
      });
    }
  });

export const taskParamsSchema = z.object({
  taskId: z.string().uuid(),
});

export const taskControlBodySchema = z.object({
  kind: z.literal("redirect"),
  instruction: z.string().trim().min(1).max(1_200),
  anchorStepId: z
    .string()
    .trim()
    .min(1)
    .max(128)
    .regex(/^[A-Za-z0-9][A-Za-z0-9._:-]*$/)
    .optional(),
});

export const taskArtifactParamsSchema = z.object({
  taskId: z.string().uuid(),
  artifactId: z.string().uuid(),
});

export const listTasksQuerySchema = z.object({
  targetDeviceId: z.string().uuid().optional(),
  status: z.string().optional(),
  limit: z.coerce.number().int().positive().max(100).default(50),
});

export const approvalBodySchema = z.object({
  approved: z.boolean(),
  notes: z.string().max(500).optional(),
  // Canonical interaction identity. `approved` and `notes` remain the legacy
  // wire fields so older mobile/runtime clients can still resolve a request.
  interactionId: z.string().trim().min(1).max(255).optional(),
  interactionRevision: z.number().int().positive().max(1_000_000).optional(),
  // Envelope-shaped aliases accepted during the additive migration.
  id: z.string().trim().min(1).max(255).optional(),
  revision: z.number().int().positive().max(1_000_000).optional(),
}).superRefine((value, ctx) => {
  if (value.interactionId && value.id && value.interactionId !== value.id) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["interactionId"],
      message: "interactionId and id must match",
    });
  }
  if (
    value.interactionRevision !== undefined &&
    value.revision !== undefined &&
    value.interactionRevision !== value.revision
  ) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["interactionRevision"],
      message: "interactionRevision and revision must match",
    });
  }
});

export const feedbackBodySchema = z.object({
  type: z.enum([
    "thumbs_up",
    "thumbs_down",
    "user_correction",
    "regenerate",
    "task_failed",
    "task_completed",
    "preferred_answer",
  ]),
  reasonTags: z
    .array(
      z.enum([
        "too_general",
        "too_long",
        "misunderstood",
        "not_warm_enough",
        "too_playful",
        "too_formal",
        "too_casual",
        "incorrect",
        "irrelevant",
      ]),
    )
    .max(5)
    .optional()
    .transform((values) => (values ? [...new Set(values)] : undefined)),
  correction: z.string().trim().max(1000).optional(),
  preferredAnswer: z.string().trim().max(2000).optional(),
});
