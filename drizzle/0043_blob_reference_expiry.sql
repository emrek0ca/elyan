ALTER TABLE "blob_references" ADD COLUMN IF NOT EXISTS "expires_at" timestamp with time zone;
CREATE INDEX IF NOT EXISTS "blob_references_expires_idx" ON "blob_references" USING btree ("expires_at");
