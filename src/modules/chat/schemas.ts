import { z } from "zod";
import { chatSessionSourceSchema, chatSessionStatusSchema } from "../../contracts/domain.js";
import { hasRawBinaryUploadHint } from "../../lib/derived-data.js";

export const createChatSessionBodySchema = z.object({
  targetDeviceId: z.string().uuid().optional(),
  source: chatSessionSourceSchema.default("mobile"),
  title: z.string().trim().min(1).max(200).optional(),
  metadata: z.record(z.any()).optional(),
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

export const createChatMessageBodySchema = z.object({
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
  metadata: z.record(z.any()).optional(),
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
  })
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
