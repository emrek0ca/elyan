CREATE TABLE IF NOT EXISTS "goal_events" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "goal_id" uuid NOT NULL REFERENCES "session_goals"("id") ON DELETE cascade,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "event_type" varchar(48) NOT NULL,
  "from_state" varchar(32),
  "to_state" varchar(32) NOT NULL,
  "payload" jsonb NOT NULL DEFAULT '{}'::jsonb,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS "goal_events_goal_created_idx"
  ON "goal_events" ("goal_id", "created_at");
CREATE INDEX IF NOT EXISTS "goal_events_user_created_idx"
  ON "goal_events" ("user_id", "created_at");
