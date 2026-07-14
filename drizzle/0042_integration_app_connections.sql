ALTER TABLE integration_connections
  ADD COLUMN IF NOT EXISTS app_id varchar(80);

-- The app-scoped flow is new. Existing provider-level connections remain
-- app_id NULL and are never leased to a curated MCP server automatically.
CREATE UNIQUE INDEX IF NOT EXISTS integration_connections_user_app_uidx
  ON integration_connections (user_id, app_id);

-- Legacy code expected one encrypted credential row but did not enforce it.
-- Keep the newest row before adding the invariant used by OAuth upserts.
DELETE FROM integration_credentials older
USING integration_credentials newer
WHERE older.connection_id = newer.connection_id
  AND (
    older.updated_at < newer.updated_at
    OR (older.updated_at = newer.updated_at AND older.id < newer.id)
  );

DROP INDEX IF EXISTS integration_credentials_connection_idx;
CREATE UNIQUE INDEX IF NOT EXISTS integration_credentials_connection_uidx
  ON integration_credentials (connection_id);
