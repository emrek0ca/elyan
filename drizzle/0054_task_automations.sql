CREATE TABLE IF NOT EXISTS "task_automations" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
  "source_task_id" uuid REFERENCES "tasks"("id") ON DELETE SET NULL,
  "target_device_id" uuid REFERENCES "devices"("id") ON DELETE SET NULL,
  "title" varchar(200) NOT NULL,
  "prompt" text NOT NULL,
  "requested_capabilities" jsonb NOT NULL DEFAULT '[]'::jsonb,
  "interval_minutes" integer NOT NULL,
  "timezone" varchar(80) NOT NULL DEFAULT 'Europe/Istanbul',
  "status" varchar(24) NOT NULL DEFAULT 'active',
  "next_run_at" timestamptz NOT NULL,
  "last_run_at" timestamptz,
  "last_task_id" uuid REFERENCES "tasks"("id") ON DELETE SET NULL,
  "last_outcome" varchar(32),
  "last_error" varchar(240),
  "failure_count" integer NOT NULL DEFAULT 0,
  "lease_until" timestamptz,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "updated_at" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "task_automations_interval_check"
    CHECK ("interval_minutes" IN (15, 60, 360, 720, 1440, 10080)),
  CONSTRAINT "task_automations_status_check"
    CHECK ("status" IN ('active', 'running', 'paused', 'canceled'))
);

CREATE INDEX IF NOT EXISTS "task_automations_user_status_next_run_idx"
  ON "task_automations" ("user_id", "status", "next_run_at");
CREATE INDEX IF NOT EXISTS "task_automations_source_task_idx"
  ON "task_automations" ("source_task_id");
CREATE INDEX IF NOT EXISTS "task_automations_last_task_idx"
  ON "task_automations" ("last_task_id");
