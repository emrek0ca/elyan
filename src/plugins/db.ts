import postgres from "postgres";
import { drizzle } from "drizzle-orm/postgres-js";
import fp from "fastify-plugin";
import * as schema from "../db/schema.js";

export const dbPlugin = fp(async (app) => {
  const sql = postgres(app.config.DATABASE_URL, {
    prepare: false,
    // Havuz sınırları: sınırsız/varsayılan havuz yüksek eşzamanlılıkta
    // Postgres'i boğar; timeout'suz connect ise istek yolunda süresiz await
    // bırakır. Değerler env üzerinden ayarlanabilir.
    max: app.config.DB_POOL_MAX,
    connect_timeout: app.config.DB_CONNECT_TIMEOUT_SECONDS,
    idle_timeout: app.config.DB_IDLE_TIMEOUT_SECONDS,
    max_lifetime: 60 * 30,
  });

  const db = drizzle(sql, { schema });
  app.decorate("db", db);

  if (app.config.ELYAN_TENANT_RLS_ENFORCEMENT_ENABLED === true) {
    const roles = await sql<Array<{ rolsuper: boolean; rolbypassrls: boolean }>>`
      SELECT rolsuper, rolbypassrls
      FROM pg_roles
      WHERE rolname = current_user
      LIMIT 1
    `;
    if (!roles[0] || roles[0].rolsuper || roles[0].rolbypassrls) {
      await sql.end({ timeout: 5 });
      throw new Error("tenant_rls_requires_restricted_database_role");
    }
  }

  app.addHook("onClose", async () => {
    await sql.end({ timeout: 5 });
  });
});
