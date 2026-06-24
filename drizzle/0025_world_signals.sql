CREATE TABLE IF NOT EXISTS "world_signals" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL,
  "device_id" uuid NOT NULL,
  "session_id" uuid,
  "client_request_id" varchar(160) NOT NULL,
  "signal_id" varchar(160) NOT NULL,
  "source" varchar(32) NOT NULL,
  "kind" varchar(32) NOT NULL,
  "summary" text NOT NULL,
  "confidence_bps" integer DEFAULT 0 NOT NULL,
  "facts" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "privacy" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "render_hints" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "visibility" varchar(64) DEFAULT 'assistant_internal_by_default' NOT NULL,
  "created_at" timestamptz NOT NULL,
  "ingested_at" timestamptz DEFAULT now() NOT NULL
);

DO $$
BEGIN
  ALTER TABLE "world_signals"
    ADD CONSTRAINT "world_signals_user_id_users_id_fk"
    FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  ALTER TABLE "world_signals"
    ADD CONSTRAINT "world_signals_device_id_devices_id_fk"
    FOREIGN KEY ("device_id") REFERENCES "public"."devices"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  ALTER TABLE "world_signals"
    ADD CONSTRAINT "world_signals_session_id_chat_sessions_id_fk"
    FOREIGN KEY ("session_id") REFERENCES "public"."chat_sessions"("id") ON DELETE set null ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS "world_signals_user_signal_uidx"
  ON "world_signals" ("user_id", "signal_id");
CREATE INDEX IF NOT EXISTS "world_signals_user_device_created_idx"
  ON "world_signals" ("user_id", "device_id", "created_at");
CREATE INDEX IF NOT EXISTS "world_signals_user_session_created_idx"
  ON "world_signals" ("user_id", "session_id", "created_at");
CREATE INDEX IF NOT EXISTS "world_signals_kind_idx"
  ON "world_signals" ("kind");
