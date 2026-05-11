import { z } from "zod";

export const auditLogQuerySchema = z.object({
  limit: z.coerce.number().int().positive().max(200).default(100),
});
