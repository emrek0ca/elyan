import { z } from "zod";
import { aiProviderSchema } from "../../contracts/domain.js";

export const routePreviewBodySchema = z.object({
  workload: z.enum(["intent", "planning", "fast_route"]),
  preferredProvider: aiProviderSchema.optional(),
  preferredModel: z.string().min(1).max(160).optional(),
  allowHosted: z.boolean().optional(),
  allowLocal: z.boolean().optional(),
});

export const aiProviderParamsSchema = z.object({
  provider: aiProviderSchema,
});

export const upsertAiCredentialBodySchema = z.object({
  label: z.string().min(1).max(120).optional(),
  apiKey: z.string().min(1).optional(),
  baseUrl: z.string().url().optional(),
  defaultModel: z.string().min(1).max(160).optional(),
  metadata: z.record(z.any()).optional(),
});

export const aiUsageQuerySchema = z.object({
  limit: z.coerce.number().int().positive().max(200).default(50),
});
