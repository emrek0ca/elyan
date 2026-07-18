import { z } from "zod";
import { mcpAuthTypeSchema, mcpServerStatusSchema, mcpTransportSchema } from "../../contracts/domain.js";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";

const shellMetaPattern = /[\0\r\n;&|`$<>]/u;
const inlineSecretArgPattern =
  /(?:^|[-_])(?:api[-_]?key|access[-_]?token|auth[-_]?token|bearer|password|passwd|secret|client[-_]?secret)(?:=|:|$)/iu;

const mcpCommandSchema = z
  .string()
  .trim()
  .min(1)
  .max(240)
  .refine((value) => !shellMetaPattern.test(value), {
    message: "MCP command cannot contain shell control characters",
  });

const mcpArgSchema = z
  .string()
  .trim()
  .min(1)
  .max(1_000)
  .refine((value) => !shellMetaPattern.test(value), {
    message: "MCP args cannot contain shell control characters",
  })
  .refine((value) => !inlineSecretArgPattern.test(value), {
    message: "MCP args cannot include inline secrets",
  });

export const createMcpServerBodySchema = z.object({
  integrationConnectionId: z.string().uuid().optional(),
  name: z.string().min(1).max(160),
  transport: mcpTransportSchema,
  authType: mcpAuthTypeSchema.default("none"),
  status: mcpServerStatusSchema.optional(),
  baseUrl: z.string().url().optional(),
  command: mcpCommandSchema.optional(),
  args: z.array(mcpArgSchema).max(64).default([]),
  config: boundedJsonRecordSchema.optional(),
  capabilities: z.array(z.string().trim().min(1).max(120)).max(128).default([]),
  metadata: boundedJsonRecordSchema.optional(),
});

export const updateMcpServerBodySchema = createMcpServerBodySchema.partial();

export const mcpServerParamsSchema = z.object({
  serverId: z.string().uuid(),
});
