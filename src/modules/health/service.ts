import { sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { supportedAiProviders } from "../ai/provider-registry.js";

export async function getReadiness(app: FastifyInstance): Promise<{
  ok: boolean;
  database: "up" | "down";
  supportedProviders: string[];
}> {
  try {
    await app.db.execute(sql`select 1`);

    return {
      ok: true,
      database: "up",
      supportedProviders: supportedAiProviders.map((provider) => provider.code),
    };
  } catch {
    return {
      ok: false,
      database: "down",
      supportedProviders: supportedAiProviders.map((provider) => provider.code),
    };
  }
}
