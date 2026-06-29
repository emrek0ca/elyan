ALTER TABLE "users"
  ADD COLUMN IF NOT EXISTS "two_factor_enabled" boolean DEFAULT false NOT NULL;

ALTER TABLE "users"
  ADD COLUMN IF NOT EXISTS "two_factor_secret_encrypted" text;

ALTER TABLE "users"
  ADD COLUMN IF NOT EXISTS "two_factor_confirmed_at" timestamptz;
