import { createHash } from "node:crypto";
import postgres from "postgres";
import { loadEnv } from "../config/env.js";

const env = loadEnv();
const db = postgres(env.DATABASE_URL, { max: 1, prepare: false });

type Mismatch = { table_name: string; row_id: string; reason_code: string };

try {
  const mismatches = await db<Mismatch[]>`
    SELECT 'dialogue_states' AS table_name, d.session_id::text AS row_id,
           'session_user_mismatch' AS reason_code
    FROM dialogue_states d
    JOIN chat_sessions s ON s.id = d.session_id
    WHERE d.user_id <> s.user_id
    UNION ALL
    SELECT 'chat_messages', m.id::text, 'session_user_mismatch'
    FROM chat_messages m
    JOIN chat_sessions s ON s.id = m.session_id
    WHERE m.user_id <> s.user_id
    UNION ALL
    SELECT 'session_goals', g.id::text, 'session_user_mismatch'
    FROM session_goals g
    JOIN chat_sessions s ON s.id = g.session_id
    WHERE g.session_id IS NOT NULL AND g.user_id <> s.user_id
    UNION ALL
    SELECT 'proactive_triggers', p.id::text, 'session_user_mismatch'
    FROM proactive_triggers p
    JOIN chat_sessions s ON s.id = p.session_id
    WHERE p.session_id IS NOT NULL AND p.user_id <> s.user_id
    LIMIT 10000
  `;

  for (const mismatch of mismatches) {
    const rowIdHash = createHash("sha256")
      .update(`${mismatch.table_name}:${mismatch.row_id}`)
      .digest("hex");
    await db`
      INSERT INTO tenant_integrity_quarantine
        (table_name, row_id_hash, reason_code)
      VALUES
        (${mismatch.table_name}, ${rowIdHash}, ${mismatch.reason_code})
      ON CONFLICT DO NOTHING
    `;
  }

  if (mismatches.length > 0) {
    process.stderr.write(`tenant integrity preflight failed: ${mismatches.length} mismatches quarantined\n`);
    process.exitCode = 1;
  } else {
    process.stdout.write("tenant integrity preflight passed\n");
  }
} finally {
  await db.end();
}
