-- Global chat workers reconcile assistant rows that were accepted without a
-- task link. Keep this partial index narrow: completed chat history and user
-- messages never participate in the orphan sweep.
CREATE INDEX IF NOT EXISTS "chat_messages_orphan_reconcile_idx"
  ON "chat_messages" ("created_at")
  WHERE "role" = 'assistant'
    AND "task_id" IS NULL
    AND "status" IN ('queued', 'running');
