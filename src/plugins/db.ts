import postgres from "postgres";
import { drizzle } from "drizzle-orm/postgres-js";
import fp from "fastify-plugin";
import * as schema from "../db/schema.js";

export const dbPlugin = fp(async (app) => {
  const sql = postgres(app.config.DATABASE_URL, {
    prepare: false,
  });

  const db = drizzle(sql, { schema });
  app.decorate("db", db);

  app.addHook("onClose", async () => {
    await sql.end({ timeout: 5 });
  });
});
