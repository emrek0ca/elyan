CREATE TABLE IF NOT EXISTS "turn_metrics" (
  "turn_id" varchar(160) PRIMARY KEY NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "session_id" uuid REFERENCES "chat_sessions"("id") ON DELETE set null,
  "workload" varchar(80) NOT NULL,
  "timings" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "quality" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS "turn_metrics_user_created_idx"
  ON "turn_metrics" ("user_id", "created_at");

CREATE INDEX IF NOT EXISTS "turn_metrics_session_created_idx"
  ON "turn_metrics" ("session_id", "created_at");

CREATE INDEX IF NOT EXISTS "turn_metrics_workload_created_idx"
  ON "turn_metrics" ("workload", "created_at");
