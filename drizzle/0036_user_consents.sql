CREATE TABLE IF NOT EXISTS "user_consents" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
  "consent_type" text NOT NULL,
  "consent_version" text NOT NULL,
  "granted" boolean NOT NULL,
  "granted_at" timestamp with time zone,
  "revoked_at" timestamp with time zone,
  "source" text,
  "metadata" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX IF NOT EXISTS "user_consents_user_type_version_uidx"
ON "user_consents" ("user_id", "consent_type", "consent_version");
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "user_consents_user_type_idx"
ON "user_consents" ("user_id", "consent_type");
