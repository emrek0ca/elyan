-- Proactive measurement.
--
-- Without this table every proactive improvement is a guess. The metric that
-- decides whether the design is right is the *mute rate*: if users silence
-- Elyan, no amount of delivery reliability makes it valuable.

CREATE TABLE IF NOT EXISTS "proactive_events" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "trigger_id" uuid REFERENCES "proactive_triggers"("id") ON DELETE set null,
  -- created | fired | suppressed | push_sent | push_failed | opened | muted | disabled | dismissed
  "event" varchar(32) NOT NULL,
  "kind" varchar(48) NOT NULL,
  "source" varchar(32) NOT NULL DEFAULT 'system',
  "reason" varchar(120),
  "detail" jsonb DEFAULT '{}'::jsonb NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL
);

CREATE INDEX IF NOT EXISTS "proactive_events_user_created_idx"
  ON "proactive_events" ("user_id", "created_at" DESC);

CREATE INDEX IF NOT EXISTS "proactive_events_event_created_idx"
  ON "proactive_events" ("event", "created_at" DESC);

CREATE INDEX IF NOT EXISTS "proactive_events_kind_created_idx"
  ON "proactive_events" ("kind", "created_at" DESC);
