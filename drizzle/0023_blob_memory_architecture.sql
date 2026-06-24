CREATE TABLE IF NOT EXISTS "blob_objects" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "content_sha256" varchar(64) NOT NULL,
  "scope" varchar(80) NOT NULL,
  "address_key" varchar(128) NOT NULL,
  "content_type" varchar(255) NOT NULL,
  "compression" varchar(32) NOT NULL DEFAULT 'identity',
  "raw_size" integer NOT NULL DEFAULT 0,
  "stored_size" integer NOT NULL DEFAULT 0,
  "storage_key" text NOT NULL,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "last_accessed_at" timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS "blob_objects_scope_hash_uidx"
  ON "blob_objects" USING btree ("scope", "content_sha256");
CREATE UNIQUE INDEX IF NOT EXISTS "blob_objects_address_uidx"
  ON "blob_objects" USING btree ("address_key");
CREATE UNIQUE INDEX IF NOT EXISTS "blob_objects_storage_key_uidx"
  ON "blob_objects" USING btree ("storage_key");
CREATE INDEX IF NOT EXISTS "blob_objects_scope_idx"
  ON "blob_objects" USING btree ("scope");

CREATE TABLE IF NOT EXISTS "blob_references" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "owner_type" varchar(64) NOT NULL,
  "owner_id" varchar(120) NOT NULL,
  "slot" varchar(80) NOT NULL,
  "blob_id" uuid NOT NULL REFERENCES "blob_objects"("id") ON DELETE CASCADE,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "deleted_at" timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS "blob_references_owner_slot_blob_uidx"
  ON "blob_references" USING btree ("owner_type", "owner_id", "slot", "blob_id");
CREATE INDEX IF NOT EXISTS "blob_references_blob_idx"
  ON "blob_references" USING btree ("blob_id");
CREATE INDEX IF NOT EXISTS "blob_references_owner_idx"
  ON "blob_references" USING btree ("owner_type", "owner_id");

ALTER TABLE "tasks"
  ADD COLUMN IF NOT EXISTS "payload_blob_id" uuid REFERENCES "blob_objects"("id") ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS "approval_request_blob_id" uuid REFERENCES "blob_objects"("id") ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS "result_blob_id" uuid REFERENCES "blob_objects"("id") ON DELETE SET NULL;

ALTER TABLE "task_events"
  ADD COLUMN IF NOT EXISTS "payload_blob_id" uuid REFERENCES "blob_objects"("id") ON DELETE SET NULL;

ALTER TABLE "realtime_events"
  ADD COLUMN IF NOT EXISTS "payload_blob_id" uuid REFERENCES "blob_objects"("id") ON DELETE SET NULL;

ALTER TABLE "artifacts"
  ADD COLUMN IF NOT EXISTS "body_blob_id" uuid REFERENCES "blob_objects"("id") ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS "content_hash" varchar(64),
  ADD COLUMN IF NOT EXISTS "byte_length" integer,
  ADD COLUMN IF NOT EXISTS "content_encoding" varchar(32),
  ADD COLUMN IF NOT EXISTS "downloadable" boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS "viewer_hint" varchar(32);

ALTER TABLE "chat_messages"
  ADD COLUMN IF NOT EXISTS "content_blob_id" uuid REFERENCES "blob_objects"("id") ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS "preview" varchar(320),
  ADD COLUMN IF NOT EXISTS "token_count" integer NOT NULL DEFAULT 0;
