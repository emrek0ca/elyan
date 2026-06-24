import postgres from "postgres";
import { drizzle } from "drizzle-orm/postgres-js";
import { loadEnv } from "../config/env.js";
import * as schema from "../db/schema.js";
import { seedBrainCorpus } from "../modules/brain/corpus.js";

try {
  process.loadEnvFile();
} catch (error) {
  const code = typeof error === "object" && error && "code" in error ? String(error.code) : "";
  if (code !== "ENOENT") {
    throw error;
  }
}

const env = loadEnv();
const sql = postgres(env.DATABASE_URL, {
  prepare: false,
});
const db = drizzle(sql, { schema });

try {
  const result = await seedBrainCorpus({
    db,
    log: {
      warn: (payload: unknown, message?: string) => {
        console.warn(message ?? "brain corpus warning", payload);
      },
    },
  } as never);
  console.log(JSON.stringify(result, null, 2));
} finally {
  await sql.end({ timeout: 5 });
}
