import { z } from "zod";
import {
  artifactInputSchema,
  taskStatusSchema,
} from "../../contracts/domain.js";
import { hasRawBinaryUploadHint } from "../../lib/derived-data.js";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";

const runtimeCapabilityHandshakeEntrySchema = z.object({
  canonicalCapabilityId: z.string().trim().min(1).max(120),
  adapter: z.string().trim().min(1).max(160),
  ready: z.boolean(),
  dependencyReady: z.boolean(),
  permissionReady: z.boolean(),
  aliases: z.array(z.string().trim().min(1).max(120)).max(16).default([]),
  version: z.string().trim().max(80).nullable().optional(),
  inputContractHash: z.string().trim().max(120).nullable().optional(),
});

const runtimeTaskAcceptanceStateSchema = z.enum([
  "accepted",
  "rejected",
  "needs_permission",
  "missing_dependency",
]);

const runtimeTaskAckFieldsSchema = z.object({
  leaseId: z.string().min(1).max(120),
  state: runtimeTaskAcceptanceStateSchema.default("accepted"),
  acceptedAt: z.string().datetime().optional(),
  missingCapabilities: z
    .array(z.string().trim().min(1).max(120))
    .max(32)
    .default([]),
  blockedReason: z.string().trim().max(300).optional(),
  consumedContractFields: z
    .array(z.string().trim().min(1).max(120))
    .max(64)
    .default([]),
});

export const registerRuntimeBodySchema = z.object({
  deviceId: z.string().uuid(),
  deviceSecret: z.string().min(16),
  runtimeVersion: z.string().min(1).max(80).optional(),
  capabilities: z.array(z.string().min(1).max(80)).default([]),
  capabilityStates: boundedJsonRecordSchema.default({}),
  capabilityHandshake: z.array(runtimeCapabilityHandshakeEntrySchema).max(256).default([]),
});

export const runtimeHeartbeatBodySchema = z.object({
  status: z.enum(["online", "busy", "idle"]).default("online"),
  currentTaskId: z.string().uuid().optional(),
  capabilities: z.array(z.string().min(1).max(80)).optional(),
  capabilityStates: boundedJsonRecordSchema.optional(),
  capabilityHandshake: z.array(runtimeCapabilityHandshakeEntrySchema).max(256).optional(),
});

export const runtimeTaskParamsSchema = z.object({
  taskId: z.string().uuid(),
});

export const runtimeTaskControlParamsSchema = z.object({
  taskId: z.string().uuid(),
  commandId: z.string().uuid(),
});

export const runtimeTaskControlAckBodySchema = z.object({
  state: z.enum(["accepted", "applied", "rejected", "failed"]),
  message: z.string().trim().max(300).optional(),
});

export const runtimeTaskAckBodySchema = runtimeTaskAckFieldsSchema;

export const runtimeTaskUpdateBodySchema = z
  .object({
    status: taskStatusSchema,
    message: z.string().max(500).optional(),
    summary: z.string().optional(),
    error: z.string().optional(),
    approvalRequest: boundedJsonRecordSchema.optional(),
    result: boundedJsonRecordSchema.optional(),
    operator: boundedJsonRecordSchema.optional(),
    artifacts: z.array(artifactInputSchema).default([]),
  })
  .superRefine((input, ctx) => {
    if (input.approvalRequest?.kind === "connector_write") {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["approvalRequest"],
        message:
          "server connector approvals cannot originate from a desktop runtime",
      });
    }

    if (hasRawBinaryUploadHint(input.approvalRequest)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["approvalRequest"],
        message:
          "raw binary upload payload is not accepted; send structured output only",
      });
    }

    if (hasRawBinaryUploadHint(input.result)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["result"],
        message:
          "raw binary upload payload is not accepted; send structured output only",
      });
    }

    if (hasRawBinaryUploadHint(input.operator)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["operator"],
        message:
          "raw binary upload payload is not accepted; send structured output only",
      });
    }
  });

export const runtimeTaskArtifactsBodySchema = z.object({
  artifacts: z.array(artifactInputSchema).min(1),
});

export const runtimeSocketMessageSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("heartbeat"),
    status: z.enum(["online", "busy", "idle"]).default("online"),
    currentTaskId: z.string().uuid().optional(),
    capabilities: z.array(z.string().min(1).max(80)).optional(),
    capabilityStates: boundedJsonRecordSchema.optional(),
    capabilityHandshake: z.array(runtimeCapabilityHandshakeEntrySchema).max(256).optional(),
  }),
  z.object({
    type: z.literal("task.ack"),
    taskId: z.string().uuid(),
  }).merge(runtimeTaskAckFieldsSchema),
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
  z.object({
    type: z.literal("task.control.ack"),
    taskId: z.string().uuid(),
    commandId: z.string().uuid(),
    state: z.enum(["accepted", "applied", "rejected", "failed"]),
    message: z.string().trim().max(300).optional(),
  }),
]);
