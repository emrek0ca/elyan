-- Push delivery channel for proactive messages.
-- Tokens live in dedicated columns (not client_metadata) so the sender can
-- look them up by index and so a metadata rewrite on re-registration can
-- never silently drop the delivery channel.

ALTER TABLE "devices"
  ADD COLUMN IF NOT EXISTS "push_token" text;

ALTER TABLE "devices"
  ADD COLUMN IF NOT EXISTS "push_provider" varchar(40);

ALTER TABLE "devices"
  ADD COLUMN IF NOT EXISTS "push_token_updated_at" timestamp with time zone;

ALTER TABLE "devices"
  ADD COLUMN IF NOT EXISTS "push_invalidated_at" timestamp with time zone;

ALTER TABLE "devices"
  ADD COLUMN IF NOT EXISTS "notification_authorization_status" varchar(40);

-- Only rows that can actually receive a push are indexed.
CREATE INDEX IF NOT EXISTS "devices_user_push_token_idx"
  ON "devices" ("user_id")
  WHERE "push_token" IS NOT NULL AND "push_invalidated_at" IS NULL;
