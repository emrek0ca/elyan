ALTER TABLE tasks
  ADD COLUMN IF NOT EXISTS execution_deadline_at timestamptz,
  ADD COLUMN IF NOT EXISTS last_progress_at timestamptz,
  ADD COLUMN IF NOT EXISTS step_revision integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS checkpoint jsonb;

CREATE INDEX IF NOT EXISTS tasks_execution_deadline_idx
  ON tasks (status, execution_deadline_at);
