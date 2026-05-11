import { z } from "zod";
import { connectionProviderSchema } from "../../contracts/domain.js";

export const oauthProviderParamsSchema = z.object({
  provider: connectionProviderSchema,
});

export const startOauthBodySchema = z.object({
  redirectUri: z.string().url().optional(),
  scopes: z.array(z.string().min(1)).optional(),
});

export const oauthCallbackQuerySchema = z.object({
  state: z.string().min(1),
  code: z.string().optional(),
  error: z.string().optional(),
  error_description: z.string().optional(),
});

export const listConnectionsQuerySchema = z.object({
  provider: connectionProviderSchema.optional(),
});

export const connectionParamsSchema = z.object({
  connectionId: z.string().uuid(),
});
