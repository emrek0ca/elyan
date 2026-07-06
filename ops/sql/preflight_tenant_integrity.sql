CREATE EXTENSION IF NOT EXISTS pgcrypto;

WITH mismatches AS (
  SELECT 'dialogue_states'::text AS table_name, d.session_id::text AS row_id,
         'session_user_mismatch'::text AS reason_code
  FROM dialogue_states d JOIN chat_sessions s ON s.id = d.session_id
  WHERE d.user_id <> s.user_id
  UNION ALL
  SELECT 'chat_messages', m.id::text, 'session_user_mismatch'
  FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id
  WHERE m.user_id <> s.user_id
  UNION ALL
  SELECT 'session_goals', g.id::text, 'session_user_mismatch'
  FROM session_goals g JOIN chat_sessions s ON s.id = g.session_id
  WHERE g.session_id IS NOT NULL AND g.user_id <> s.user_id
  UNION ALL
  SELECT 'proactive_triggers', p.id::text, 'session_user_mismatch'
  FROM proactive_triggers p JOIN chat_sessions s ON s.id = p.session_id
  WHERE p.session_id IS NOT NULL AND p.user_id <> s.user_id
)
INSERT INTO tenant_integrity_quarantine (table_name, row_id_hash, reason_code)
SELECT table_name, encode(digest(table_name || ':' || row_id, 'sha256'), 'hex'), reason_code
FROM mismatches
ON CONFLICT DO NOTHING;

DO $$
DECLARE
  mismatch_count bigint;
BEGIN
  SELECT count(*) INTO mismatch_count
  FROM tenant_integrity_quarantine
  WHERE resolved_at IS NULL;
  IF mismatch_count > 0 THEN
    RAISE EXCEPTION 'tenant integrity preflight failed: % unresolved mismatches', mismatch_count;
  END IF;
END $$;
