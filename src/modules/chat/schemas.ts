import { z } from "zod";
import { chatSessionSourceSchema, chatSessionStatusSchema } from "../../contracts/domain.js";
import { hasRawBinaryUploadHint } from "../../lib/derived-data.js";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";
import { ephemeralVisionCarrierSchema } from "../brain/ephemeral-vision.js";

export const createChatSessionBodySchema = z.object({
  targetDeviceId: z.string().uuid().optional(),
  source: chatSessionSourceSchema.default("mobile"),
  title: z.string().trim().min(1).max(200).optional(),
  metadata: boundedJsonRecordSchema.optional(),
}).superRefine((input, ctx) => {
  if (hasRawBinaryUploadHint(input.metadata)) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["metadata"],
      message: "raw binary upload payload is not accepted; send processed data only",
    });
  }
});

const chatInputBlockSchema = z.object({
  type: z.literal("text"),
  markdown: z.string().trim().min(1).max(20_000),
}).passthrough();

function contentFromInputBlocks(blocks: Array<z.infer<typeof chatInputBlockSchema>> | undefined): string {
  return (blocks ?? [])
    .filter((block) => block.type === "text")
    .map((block) => block.markdown.trim())
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

function normalizeAuthorizedLegacyVision(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const input = { ...(value as Record<string, unknown>) };
  const directVision = input.ephemeralVision;
  if (directVision && typeof directVision === "object" && !Array.isArray(directVision)) {
    const carrier = directVision as Record<string, unknown>;
    if (carrier.version === 2 && Array.isArray(carrier.inputRefs)) {
      const metadata = input.metadata && typeof input.metadata === "object" && !Array.isArray(input.metadata)
        ? { ...(input.metadata as Record<string, unknown>) }
        : {};
      metadata.mediaInputRefs = carrier.inputRefs;
      input.metadata = metadata;
    }
    return input;
  }
  const metadataValue = input.metadata;
  if (!metadataValue || typeof metadataValue !== "object" || Array.isArray(metadataValue)) return input;
  const metadata = { ...(metadataValue as Record<string, unknown>) };
  if (metadata.cloudVisionOptIn !== true || !Array.isArray(metadata.attachments)) return input;

  const images: Array<Record<string, unknown>> = [];
  const attachments = metadata.attachments.map((value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return value;
    const attachment = { ...(value as Record<string, unknown>) };
    if (!Array.isArray(attachment.clientAttachments)) return attachment;
    const retained: unknown[] = [];
    for (const nested of attachment.clientAttachments) {
      if (!nested || typeof nested !== "object" || Array.isArray(nested)) {
        retained.push(nested);
        continue;
      }
      const item = nested as Record<string, unknown>;
      if (item.attachmentType !== "image" || typeof item.base64Thumbnail !== "string") {
        retained.push(nested);
        continue;
      }
      images.push({
        imageId: String(item.imageId ?? attachment.documentId ?? `legacy-image-${images.length + 1}`).slice(0, 120),
        kind: "full_frame",
        mimeType: ["image/jpeg", "image/png", "image/webp"].includes(String(item.mimeType))
          ? item.mimeType
          : "image/jpeg",
        base64Data: item.base64Thumbnail,
        width: Number(item.thumbnailWidth) || 512,
        height: Number(item.thumbnailHeight) || 512,
      });
    }
    if (retained.length > 0) attachment.clientAttachments = retained;
    else delete attachment.clientAttachments;
    return attachment;
  });
  if (images.length === 0) return input;
  metadata.attachments = attachments;
  input.metadata = metadata;
  input.ephemeralVision = {
    version: 1,
    retention: "request_ephemeral",
    privacy: {
      metadataStripped: true,
      userAuthorizedCloud: true,
      localSensitivity: "personal",
    },
    images: images.slice(0, 4),
  };
  return input;
}

export const createChatMessageBodySchema = z.preprocess(normalizeAuthorizedLegacyVision, z.object({
  sessionId: z.string().uuid().optional(),
  chatSessionId: z.string().uuid().optional(),
  targetDeviceId: z.string().uuid().optional(),
  source: chatSessionSourceSchema.default("mobile"),
  title: z.string().trim().min(1).max(200).optional(),
  content: z.string().trim().min(1).max(20_000).optional(),
  blocks: z.array(chatInputBlockSchema).max(8).optional(),
  requestedCapabilities: z
    .array(z.string().trim().min(1).max(80))
    .max(20)
    .transform((values) => [...new Set(values)])
    .default([]),
  metadata: boundedJsonRecordSchema.optional(),
  ephemeralVision: ephemeralVisionCarrierSchema.optional(),
})
  .superRefine((input, ctx) => {
    const content = input.content?.trim() || contentFromInputBlocks(input.blocks);
    if (!content) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["blocks"],
        message: "content must be provided as an Elyan text block",
      });
    }
    if (
      input.sessionId &&
      input.chatSessionId &&
      input.sessionId !== input.chatSessionId
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["chatSessionId"],
        message: "chatSessionId must match sessionId when both are provided",
      });
    }
    if (hasRawBinaryUploadHint(input.metadata)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["metadata"],
        message: "raw binary upload payload is not accepted; send processed data only",
      });
    }
  }))
  .transform(({ chatSessionId, ...input }) => {
    const content = input.content?.trim() || contentFromInputBlocks(input.blocks);
    return {
      ...input,
      content,
      sessionId: input.sessionId ?? chatSessionId,
    };
  });

export const updateChatSessionBodySchema = z
  .object({
    status: chatSessionStatusSchema.optional(),
    title: z.string().trim().min(1).max(200).optional(),
  })
  .refine((body) => body.status !== undefined || body.title !== undefined, {
    message: "At least one chat session field must be provided",
  });

export const chatSessionParamsSchema = z.object({
  sessionId: z.string().uuid(),
});

export const clearChatSessionsQuerySchema = z.object({
  before: z.coerce.date().optional(),
});

export const listChatSessionsQuerySchema = z.object({
  status: chatSessionStatusSchema.optional(),
  cursor: z.string().trim().min(1).optional(),
  limit: z.coerce.number().int().positive().max(20).default(20),
});

export const listChatSessionMessagesQuerySchema = z.object({
  cursor: z.string().trim().min(1).optional(),
  limit: z.coerce.number().int().positive().max(50).optional(),
});
