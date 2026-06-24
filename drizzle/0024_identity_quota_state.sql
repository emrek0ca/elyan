DO $$
BEGIN
  CREATE TYPE "usage_window_type" AS ENUM ('daily', 'weekly');
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE TABLE IF NOT EXISTS "user_identity_history" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "normalized_email" varchar(320) NOT NULL,
  "first_user_id" uuid,
  "latest_user_id" uuid,
  "created_at" timestamptz DEFAULT now() NOT NULL,
  "updated_at" timestamptz DEFAULT now() NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS "user_identity_history_normalized_email_uidx"
  ON "user_identity_history" ("normalized_email");
CREATE INDEX IF NOT EXISTS "user_identity_history_latest_user_idx"
  ON "user_identity_history" ("latest_user_id");

DO $$
BEGIN
  ALTER TABLE "user_identity_history"
    ADD CONSTRAINT "user_identity_history_first_user_id_users_id_fk"
    FOREIGN KEY ("first_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

DO $$
BEGIN
  ALTER TABLE "user_identity_history"
    ADD CONSTRAINT "user_identity_history_latest_user_id_users_id_fk"
    FOREIGN KEY ("latest_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "identity_id" uuid;
ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "deleted_at" timestamptz;

DO $$
BEGIN
  ALTER TABLE "users"
    ADD CONSTRAINT "users_identity_id_user_identity_history_id_fk"
    FOREIGN KEY ("identity_id") REFERENCES "public"."user_identity_history"("id") ON DELETE set null ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE INDEX IF NOT EXISTS "users_identity_idx" ON "users" ("identity_id");
CREATE INDEX IF NOT EXISTS "users_deleted_at_idx" ON "users" ("deleted_at");

ALTER TABLE "usage_records" ADD COLUMN IF NOT EXISTS "identity_id" uuid;
ALTER TABLE "usage_records" ADD COLUMN IF NOT EXISTS "budget_units" integer DEFAULT 0 NOT NULL;
ALTER TABLE "usage_records" ADD COLUMN IF NOT EXISTS "document_units" integer DEFAULT 0 NOT NULL;
ALTER TABLE "usage_records" ADD COLUMN IF NOT EXISTS "image_units" integer DEFAULT 0 NOT NULL;
ALTER TABLE "usage_records" ADD COLUMN IF NOT EXISTS "tool_units" integer DEFAULT 0 NOT NULL;
ALTER TABLE "usage_records" ADD COLUMN IF NOT EXISTS "quality_profile" varchar(32);
ALTER TABLE "usage_records" ADD COLUMN IF NOT EXISTS "plan_snapshot" jsonb DEFAULT '{}'::jsonb NOT NULL;

DO $$
BEGIN
  ALTER TABLE "usage_records"
    ADD CONSTRAINT "usage_records_identity_id_user_identity_history_id_fk"
    FOREIGN KEY ("identity_id") REFERENCES "public"."user_identity_history"("id") ON DELETE set null ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE INDEX IF NOT EXISTS "usage_records_identity_idx" ON "usage_records" ("identity_id");

INSERT INTO "user_identity_history" (
  "normalized_email",
  "first_user_id",
  "latest_user_id",
  "created_at",
  "updated_at"
)
SELECT
  lower(trim("email")) AS "normalized_email",
  "id" AS "first_user_id",
  "id" AS "latest_user_id",
  "created_at",
  "updated_at"
FROM "users"
WHERE trim(coalesce("email", '')) <> ''
ON CONFLICT ("normalized_email") DO UPDATE
SET
  "latest_user_id" = EXCLUDED."latest_user_id",
  "updated_at" = GREATEST("user_identity_history"."updated_at", EXCLUDED."updated_at");

UPDATE "users"
SET "identity_id" = "user_identity_history"."id"
FROM "user_identity_history"
WHERE "users"."identity_id" IS NULL
  AND "user_identity_history"."normalized_email" = lower(trim("users"."email"));

UPDATE "usage_records"
SET
  "identity_id" = "users"."identity_id",
  "budget_units" = CASE
    WHEN "usage_records"."budget_units" > 0 THEN "usage_records"."budget_units"
    WHEN "usage_records"."metric" IN ('subscription_ai_credit', 'trial_task') THEN GREATEST("usage_records"."quantity", 0)
    ELSE 0
  END
FROM "users"
WHERE "usage_records"."user_id" = "users"."id"
  AND "users"."identity_id" IS NOT NULL;

CREATE TABLE IF NOT EXISTS "quota_state" (
  "identity_id" uuid PRIMARY KEY NOT NULL,
  "daily_used_units" integer DEFAULT 0 NOT NULL,
  "weekly_used_units" integer DEFAULT 0 NOT NULL,
  "daily_reset_at" timestamptz DEFAULT (now() + interval '24 hours') NOT NULL,
  "weekly_reset_at" timestamptz DEFAULT (now() + interval '7 days') NOT NULL,
  "document_upload_count" integer DEFAULT 0 NOT NULL,
  "image_upload_count" integer DEFAULT 0 NOT NULL,
  "created_at" timestamptz DEFAULT now() NOT NULL,
  "updated_at" timestamptz DEFAULT now() NOT NULL
);

DO $$
BEGIN
  ALTER TABLE "quota_state"
    ADD CONSTRAINT "quota_state_identity_id_user_identity_history_id_fk"
    FOREIGN KEY ("identity_id") REFERENCES "public"."user_identity_history"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE INDEX IF NOT EXISTS "quota_state_daily_reset_idx" ON "quota_state" ("daily_reset_at");
CREATE INDEX IF NOT EXISTS "quota_state_weekly_reset_idx" ON "quota_state" ("weekly_reset_at");

INSERT INTO "quota_state" (
  "identity_id",
  "daily_used_units",
  "weekly_used_units",
  "daily_reset_at",
  "weekly_reset_at",
  "document_upload_count",
  "image_upload_count",
  "created_at",
  "updated_at"
)
SELECT
  "uih"."id" AS "identity_id",
  COALESCE(SUM(
    CASE
      WHEN "ur"."created_at" >= now() - interval '24 hours'
        THEN CASE
          WHEN COALESCE("ur"."budget_units", 0) > 0 THEN "ur"."budget_units"
          WHEN "ur"."metric" IN ('subscription_ai_credit', 'trial_task') THEN GREATEST("ur"."quantity", 0)
          ELSE 0
        END
      ELSE 0
    END
  ), 0) AS "daily_used_units",
  COALESCE(SUM(
    CASE
      WHEN "ur"."created_at" >= now() - interval '7 days'
        THEN CASE
          WHEN COALESCE("ur"."budget_units", 0) > 0 THEN "ur"."budget_units"
          WHEN "ur"."metric" IN ('subscription_ai_credit', 'trial_task') THEN GREATEST("ur"."quantity", 0)
          ELSE 0
        END
      ELSE 0
    END
  ), 0) AS "weekly_used_units",
  COALESCE(
    MIN("ur"."created_at") FILTER (WHERE "ur"."created_at" >= now() - interval '24 hours') + interval '24 hours',
    now() + interval '24 hours'
  ) AS "daily_reset_at",
  COALESCE(
    MIN("ur"."created_at") FILTER (WHERE "ur"."created_at" >= now() - interval '7 days') + interval '7 days',
    now() + interval '7 days'
  ) AS "weekly_reset_at",
  COALESCE(SUM(CASE WHEN "ur"."created_at" >= now() - interval '7 days' THEN COALESCE("ur"."document_units", 0) ELSE 0 END), 0) AS "document_upload_count",
  COALESCE(SUM(CASE WHEN "ur"."created_at" >= now() - interval '7 days' THEN COALESCE("ur"."image_units", 0) ELSE 0 END), 0) AS "image_upload_count",
  now(),
  now()
FROM "user_identity_history" "uih"
LEFT JOIN "usage_records" "ur"
  ON "ur"."identity_id" = "uih"."id"
GROUP BY "uih"."id"
ON CONFLICT ("identity_id") DO UPDATE
SET
  "daily_used_units" = EXCLUDED."daily_used_units",
  "weekly_used_units" = EXCLUDED."weekly_used_units",
  "daily_reset_at" = EXCLUDED."daily_reset_at",
  "weekly_reset_at" = EXCLUDED."weekly_reset_at",
  "document_upload_count" = EXCLUDED."document_upload_count",
  "image_upload_count" = EXCLUDED."image_upload_count",
  "updated_at" = now();

CREATE TABLE IF NOT EXISTS "usage_windows" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
  "identity_id" uuid NOT NULL,
  "window_type" "usage_window_type" NOT NULL,
  "window_started_at" timestamptz NOT NULL,
  "window_ends_at" timestamptz NOT NULL,
  "used_units" integer DEFAULT 0 NOT NULL,
  "document_upload_count" integer DEFAULT 0 NOT NULL,
  "image_upload_count" integer DEFAULT 0 NOT NULL,
  "created_at" timestamptz DEFAULT now() NOT NULL,
  "updated_at" timestamptz DEFAULT now() NOT NULL
);

DO $$
BEGIN
  ALTER TABLE "usage_windows"
    ADD CONSTRAINT "usage_windows_identity_id_user_identity_history_id_fk"
    FOREIGN KEY ("identity_id") REFERENCES "public"."user_identity_history"("id") ON DELETE cascade ON UPDATE no action;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS "usage_windows_identity_window_uidx"
  ON "usage_windows" ("identity_id", "window_type");
CREATE INDEX IF NOT EXISTS "usage_windows_identity_idx"
  ON "usage_windows" ("identity_id");

INSERT INTO "usage_windows" (
  "identity_id",
  "window_type",
  "window_started_at",
  "window_ends_at",
  "used_units",
  "document_upload_count",
  "image_upload_count",
  "created_at",
  "updated_at"
)
SELECT
  "identity_id",
  'daily'::"usage_window_type",
  now() - interval '24 hours',
  "daily_reset_at",
  "daily_used_units",
  0,
  0,
  now(),
  now()
FROM "quota_state"
ON CONFLICT ("identity_id", "window_type") DO UPDATE
SET
  "window_started_at" = EXCLUDED."window_started_at",
  "window_ends_at" = EXCLUDED."window_ends_at",
  "used_units" = EXCLUDED."used_units",
  "updated_at" = now();

INSERT INTO "usage_windows" (
  "identity_id",
  "window_type",
  "window_started_at",
  "window_ends_at",
  "used_units",
  "document_upload_count",
  "image_upload_count",
  "created_at",
  "updated_at"
)
SELECT
  "identity_id",
  'weekly'::"usage_window_type",
  now() - interval '7 days',
  "weekly_reset_at",
  "weekly_used_units",
  "document_upload_count",
  "image_upload_count",
  now(),
  now()
FROM "quota_state"
ON CONFLICT ("identity_id", "window_type") DO UPDATE
SET
  "window_started_at" = EXCLUDED."window_started_at",
  "window_ends_at" = EXCLUDED."window_ends_at",
  "used_units" = EXCLUDED."used_units",
  "document_upload_count" = EXCLUDED."document_upload_count",
  "image_upload_count" = EXCLUDED."image_upload_count",
  "updated_at" = now();
