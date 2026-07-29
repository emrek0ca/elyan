-- Night watch + autonomous suggestion generation.

-- A suggestion the observer derived from a signal must not be re-created on
-- every sweep. The dedupe key is a stable hash of (kind, subject) and is only
-- unique among triggers that have not resolved yet, so the same subject can
-- legitimately come back weeks later.
ALTER TABLE "proactive_triggers"
  ADD COLUMN IF NOT EXISTS "dedupe_key" varchar(160);

CREATE UNIQUE INDEX IF NOT EXISTS "proactive_triggers_user_dedupe_open_uidx"
  ON "proactive_triggers" ("user_id", "dedupe_key")
  WHERE "dedupe_key" IS NOT NULL AND "status" IN ('pending', 'running');

-- One row per unit of work Elyan takes on overnight. Kept out of the trigger
-- payload on purpose: the morning digest reports on facts, and facts belong in
-- queryable rows, not in a blob we would have to trust.
CREATE TABLE IF NOT EXISTS "night_watch_jobs" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "night_date" date NOT NULL,
  "device_id" uuid REFERENCES "devices"("id") ON DELETE set null,
  "task_id" uuid REFERENCES "tasks"("id") ON DELETE set null,
  "session_id" uuid REFERENCES "chat_sessions"("id") ON DELETE set null,
  "title" varchar(200) NOT NULL,
  "prompt" text NOT NULL,
  "capabilities" jsonb DEFAULT '[]'::jsonb NOT NULL,
  -- Why Elyan thought this was worth doing. Never null: a job with no
  -- traceable origin is exactly the fabrication we are guarding against.
  "evidence" jsonb NOT NULL,
  "fingerprint" varchar(64) NOT NULL,
  "status" varchar(32) DEFAULT 'planned' NOT NULL,
  "status_reason" varchar(120),
  "result_summary" text,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "dispatched_at" timestamp with time zone,
  "settled_at" timestamp with time zone,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS "night_watch_jobs_user_night_fingerprint_uidx"
  ON "night_watch_jobs" ("user_id", "night_date", "fingerprint");

CREATE INDEX IF NOT EXISTS "night_watch_jobs_user_night_idx"
  ON "night_watch_jobs" ("user_id", "night_date");

CREATE INDEX IF NOT EXISTS "night_watch_jobs_status_idx"
  ON "night_watch_jobs" ("status");
