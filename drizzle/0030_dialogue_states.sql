CREATE TABLE IF NOT EXISTS "dialogue_states" (
  "session_id" uuid PRIMARY KEY NOT NULL REFERENCES "chat_sessions"("id") ON DELETE cascade,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "revision" integer DEFAULT 0 NOT NULL,
  "state" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS "dialogue_states_user_updated_idx"
  ON "dialogue_states" ("user_id", "updated_at");
