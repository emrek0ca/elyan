import { z } from "zod";
import { mcpAuthTypeSchema, mcpServerStatusSchema, mcpTransportSchema } from "../../contracts/domain.js";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";

export const createMcpServerBodySchema = z.object({
  integrationConnectionId: z.string().uuid().optional(),
  name: z.string().min(1).max(160),
  transport: mcpTransportSchema,
  authType: mcpAuthTypeSchema.default("none"),
  status: mcpServerStatusSchema.optional(),
  baseUrl: z.string().url().optional(),
  command: z.string().min(1).optional(),
  args: z.array(z.string().min(1)).default([]),
  config: boundedJsonRecordSchema.optional(),
  capabilities: z.array(z.string().min(1)).default([]),
  metadata: boundedJsonRecordSchema.optional(),
});

export const updateMcpServerBodySchema = createMcpServerBodySchema.partial();

export const mcpServerParamsSchema = z.object({
  serverId: z.string().uuid(),
});
