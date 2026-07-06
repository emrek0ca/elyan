CREATE UNIQUE INDEX IF NOT EXISTS "chat_sessions_id_user_uidx"
  ON "chat_sessions" ("id", "user_id");

CREATE INDEX IF NOT EXISTS "task_events_task_created_idx"
  ON "task_events" ("task_id", "created_at" DESC);

DO $$
BEGIN
  IF to_regclass('public.goal_events') IS NOT NULL THEN
    CREATE INDEX IF NOT EXISTS "goal_events_goal_user_created_idx"
      ON "goal_events" ("goal_id", "user_id", "created_at" DESC);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'dialogue_states_session_user_fk'
  ) THEN
    ALTER TABLE "dialogue_states"
      ADD CONSTRAINT "dialogue_states_session_user_fk"
      FOREIGN KEY ("session_id", "user_id")
      REFERENCES "chat_sessions" ("id", "user_id")
      ON DELETE CASCADE
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chat_messages_session_user_fk'
  ) THEN
    ALTER TABLE "chat_messages"
      ADD CONSTRAINT "chat_messages_session_user_fk"
      FOREIGN KEY ("session_id", "user_id")
      REFERENCES "chat_sessions" ("id", "user_id")
      ON DELETE CASCADE
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'session_goals_session_user_fk'
  ) THEN
    ALTER TABLE "session_goals"
      ADD CONSTRAINT "session_goals_session_user_fk"
      FOREIGN KEY ("session_id", "user_id")
      REFERENCES "chat_sessions" ("id", "user_id")
      ON DELETE CASCADE
      NOT VALID;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'proactive_triggers_session_user_fk'
  ) THEN
    ALTER TABLE "proactive_triggers"
      ADD CONSTRAINT "proactive_triggers_session_user_fk"
      FOREIGN KEY ("session_id", "user_id")
      REFERENCES "chat_sessions" ("id", "user_id")
      ON DELETE CASCADE
      NOT VALID;
  END IF;
END $$;
