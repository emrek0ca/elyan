CREATE TABLE IF NOT EXISTS "proactive_triggers" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL,
  "session_id" uuid,
  "kind" varchar(40) DEFAULT 'follow_up' NOT NULL,
  "due" timestamp with time zone NOT NULL,
  "payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "status" varchar(32) DEFAULT 'pending' NOT NULL,
  "created_by" varchar(32) DEFAULT 'model' NOT NULL,
  "fired_at" timestamp with time zone,
  "canceled_at" timestamp with time zone,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'proactive_triggers_user_id_users_id_fk'
      AND conrelid = 'proactive_triggers'::regclass
  ) THEN
    ALTER TABLE "proactive_triggers"
      ADD CONSTRAINT "proactive_triggers_user_id_users_id_fk"
      FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'proactive_triggers_session_id_chat_sessions_id_fk'
      AND conrelid = 'proactive_triggers'::regclass
  ) THEN
    ALTER TABLE "proactive_triggers"
      ADD CONSTRAINT "proactive_triggers_session_id_chat_sessions_id_fk"
      FOREIGN KEY ("session_id") REFERENCES "public"."chat_sessions"("id") ON DELETE cascade ON UPDATE no action;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS "proactive_triggers_user_due_idx"
  ON "proactive_triggers" USING btree ("user_id","due");
CREATE INDEX IF NOT EXISTS "proactive_triggers_session_due_idx"
  ON "proactive_triggers" USING btree ("session_id","due");
CREATE INDEX IF NOT EXISTS "proactive_triggers_status_due_idx"
  ON "proactive_triggers" USING btree ("status","due");
CREATE INDEX IF NOT EXISTS "proactive_triggers_kind_status_idx"
  ON "proactive_triggers" USING btree ("kind","status");
