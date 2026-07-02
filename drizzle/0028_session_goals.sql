DO $$ BEGIN
  CREATE TYPE session_goal_status AS ENUM ('draft', 'active', 'paused', 'done', 'canceled');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE session_goal_schedule_hint AS ENUM ('on_next_message', 'daily_08_00', 'every_15m');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS "session_goals" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "session_id" uuid REFERENCES "chat_sessions"("id") ON DELETE cascade,
  "task_id" uuid REFERENCES "tasks"("id") ON DELETE set null,
  "title" varchar(200) NOT NULL,
  "description" text NOT NULL DEFAULT '',
  "status" session_goal_status NOT NULL DEFAULT 'active',
  "current_step" integer NOT NULL DEFAULT 0,
  "max_steps" integer NOT NULL DEFAULT 20,
  "progress" jsonb NOT NULL DEFAULT '{}'::jsonb,
  "schedule_hint" session_goal_schedule_hint,
  "due_at" timestamp with time zone,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS "session_goals_user_status_idx"
  ON "session_goals" ("user_id", "status");
CREATE INDEX IF NOT EXISTS "session_goals_session_status_idx"
  ON "session_goals" ("session_id", "status");
CREATE INDEX IF NOT EXISTS "session_goals_task_idx"
  ON "session_goals" ("task_id");
CREATE INDEX IF NOT EXISTS "session_goals_due_idx"
  ON "session_goals" ("due_at");
