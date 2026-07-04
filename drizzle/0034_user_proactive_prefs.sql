CREATE TABLE IF NOT EXISTS "user_proactive_prefs" (
  "user_id" uuid PRIMARY KEY NOT NULL REFERENCES "users"("id") ON DELETE cascade,
  "enabled" boolean DEFAULT true NOT NULL,
  "max_daily" integer DEFAULT 3 NOT NULL,
  "quiet_start_hour" integer DEFAULT 22 NOT NULL,
  "quiet_end_hour" integer DEFAULT 8 NOT NULL,
  "timezone" varchar(80) DEFAULT 'Europe/Istanbul' NOT NULL,
  "muted_kinds" jsonb DEFAULT '[]'::jsonb NOT NULL,
  "created_at" timestamp with time zone DEFAULT now() NOT NULL,
  "updated_at" timestamp with time zone DEFAULT now() NOT NULL,
  CONSTRAINT "user_proactive_prefs_max_daily_check" CHECK ("max_daily" BETWEEN 0 AND 20),
  CONSTRAINT "user_proactive_prefs_quiet_start_check" CHECK ("quiet_start_hour" BETWEEN 0 AND 23),
  CONSTRAINT "user_proactive_prefs_quiet_end_check" CHECK ("quiet_end_hour" BETWEEN 0 AND 23)
);
