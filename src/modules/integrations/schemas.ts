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
  state: z.string().min(1).max(200),
  code: z.string().max(4096).optional(),
  error: z.string().max(120).optional(),
  error_description: z.string().max(500).optional(),
});

export const listConnectionsQuerySchema = z.object({
  provider: connectionProviderSchema.optional(),
});

export const connectionParamsSchema = z.object({
  connectionId: z.string().uuid(),
});

export const integrationAppParamsSchema = z.object({
  appId: z.string().trim().min(1).max(80).regex(/^[a-z0-9-]+$/),
});

export const startAppOauthBodySchema = z.object({
  redirectUri: z.string().url().optional(),
});

export const sendGmailBodySchema = z.object({
  connectionId: z.string().uuid().optional(),
  to: z.array(z.string().email()).min(1).max(10),
  subject: z.string().trim().min(1).max(300),
  body: z.string().trim().min(1).max(20_000),
  cc: z.array(z.string().email()).max(10).optional(),
  bcc: z.array(z.string().email()).max(10).optional(),
  replyTo: z.string().email().optional(),
});
