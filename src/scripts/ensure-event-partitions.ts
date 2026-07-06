import postgres from "postgres";
import { loadEnv } from "../config/env.js";

const env = loadEnv();
const db = postgres(env.DATABASE_URL, { max: 1, prepare: false });

try {
  await db`SELECT elyan_ensure_event_partitions(3)`;
  await db`SELECT elyan_ensure_agent_event_partitions(CURRENT_DATE)`;
  process.stdout.write("event partitions ensured; agent partitions cover the next twelve months\n");
} finally {
  await db.end();
}
