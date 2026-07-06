ALTER TABLE "brain_memory_facts"
  ADD COLUMN IF NOT EXISTS "valid_from" timestamptz,
  ADD COLUMN IF NOT EXISTS "valid_to" timestamptz,
  ADD COLUMN IF NOT EXISTS "observed_at" timestamptz,
  ADD COLUMN IF NOT EXISTS "revision" integer,
  ADD COLUMN IF NOT EXISTS "source_kind" varchar(48),
  ADD COLUMN IF NOT EXISTS "source_id" varchar(160),
  ADD COLUMN IF NOT EXISTS "content_hash" varchar(64);

UPDATE "brain_memory_facts"
SET
  "valid_from" = COALESCE("valid_from", "created_at"),
  "observed_at" = COALESCE("observed_at", "last_verified_at", "created_at"),
  "revision" = COALESCE("revision", 1),
  "source_kind" = COALESCE("source_kind", 'legacy'),
  "valid_to" = CASE
    WHEN "lifecycle_status" IN ('superseded', 'soft_deleted') THEN COALESCE("valid_to", "updated_at")
    ELSE "valid_to"
  END;

ALTER TABLE "brain_memory_facts"
  ALTER COLUMN "valid_from" SET DEFAULT now(),
  ALTER COLUMN "valid_from" SET NOT NULL,
  ALTER COLUMN "observed_at" SET DEFAULT now(),
  ALTER COLUMN "observed_at" SET NOT NULL,
  ALTER COLUMN "revision" SET DEFAULT 1,
  ALTER COLUMN "revision" SET NOT NULL,
  ALTER COLUMN "source_kind" SET DEFAULT 'legacy',
  ALTER COLUMN "source_kind" SET NOT NULL;

ALTER TABLE "brain_memory_episodes"
  ADD COLUMN IF NOT EXISTS "observed_at" timestamptz,
  ADD COLUMN IF NOT EXISTS "expires_at" timestamptz,
  ADD COLUMN IF NOT EXISTS "revision" integer,
  ADD COLUMN IF NOT EXISTS "source_kind" varchar(48),
  ADD COLUMN IF NOT EXISTS "source_id" varchar(160),
  ADD COLUMN IF NOT EXISTS "content_hash" varchar(64);

UPDATE "brain_memory_episodes"
SET
  "observed_at" = COALESCE("observed_at", "started_at", "created_at"),
  "expires_at" = COALESCE("expires_at", "created_at" + interval '90 days'),
  "revision" = COALESCE("revision", 1),
  "source_kind" = COALESCE("source_kind", 'legacy');

ALTER TABLE "brain_memory_episodes"
  ALTER COLUMN "observed_at" SET DEFAULT now(),
  ALTER COLUMN "observed_at" SET NOT NULL,
  ALTER COLUMN "expires_at" SET DEFAULT (now() + interval '90 days'),
  ALTER COLUMN "expires_at" SET NOT NULL,
  ALTER COLUMN "revision" SET DEFAULT 1,
  ALTER COLUMN "revision" SET NOT NULL,
  ALTER COLUMN "source_kind" SET DEFAULT 'legacy',
  ALTER COLUMN "source_kind" SET NOT NULL;

CREATE TABLE IF NOT EXISTS "cognitive_memory_revisions" (
  "user_id" uuid PRIMARY KEY REFERENCES "users"("id") ON DELETE CASCADE,
  "revision" integer NOT NULL DEFAULT 0,
  "updated_at" timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS "cognitive_mutation_outbox" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
  "session_id" uuid,
  "revision" integer NOT NULL,
  "event_type" varchar(64) NOT NULL,
  "payload" jsonb NOT NULL DEFAULT '{}'::jsonb,
  "status" varchar(24) NOT NULL DEFAULT 'pending',
  "attempts" integer NOT NULL DEFAULT 0,
  "available_at" timestamptz NOT NULL DEFAULT now(),
  "processed_at" timestamptz,
  "last_error_code" varchar(96),
  "created_at" timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS "tenant_integrity_quarantine" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "table_name" varchar(96) NOT NULL,
  "row_id_hash" varchar(64) NOT NULL,
  "reason_code" varchar(96) NOT NULL,
  "detected_at" timestamptz NOT NULL DEFAULT now(),
  "resolved_at" timestamptz
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'cognitive_outbox_session_user_fk'
  ) THEN
    ALTER TABLE cognitive_mutation_outbox
      ADD CONSTRAINT cognitive_outbox_session_user_fk
      FOREIGN KEY (session_id, user_id)
      REFERENCES chat_sessions(id, user_id)
      ON DELETE CASCADE
      NOT VALID;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS "brain_memory_facts_user_temporal_idx"
  ON "brain_memory_facts" ("user_id", "canonical_key", "valid_from" DESC);
CREATE INDEX IF NOT EXISTS "brain_memory_episodes_user_expiry_idx"
  ON "brain_memory_episodes" ("user_id", "expires_at");
CREATE INDEX IF NOT EXISTS "cognitive_mutation_outbox_pending_idx"
  ON "cognitive_mutation_outbox" ("status", "available_at");
CREATE UNIQUE INDEX IF NOT EXISTS "cognitive_mutation_outbox_user_revision_uidx"
  ON "cognitive_mutation_outbox" ("user_id", "revision");
CREATE INDEX IF NOT EXISTS "tenant_integrity_quarantine_unresolved_idx"
  ON "tenant_integrity_quarantine" ("table_name", "resolved_at");
CREATE UNIQUE INDEX IF NOT EXISTS "tenant_integrity_quarantine_open_uidx"
  ON "tenant_integrity_quarantine" ("table_name", "row_id_hash", "reason_code")
  WHERE "resolved_at" IS NULL;

DO $$
DECLARE
  available_kinds text;
BEGIN
  SELECT string_agg(quote_literal(label), ', ' ORDER BY label)
  INTO available_kinds
  FROM (
    SELECT enumlabel AS label
    FROM pg_enum
    WHERE enumtypid = 'training_job_kind'::regtype
      AND enumlabel IN ('memory_extraction', 'memory_consolidation', 'memory_index', 'memory_decay')
  ) labels;

  IF available_kinds IS NOT NULL THEN
    EXECUTE format(
      'CREATE UNIQUE INDEX IF NOT EXISTS training_jobs_active_memory_user_kind_uidx
       ON training_jobs (owner_user_id, kind)
       WHERE owner_user_id IS NOT NULL
         AND kind IN (%s)
         AND status IN (''queued'', ''running'')',
      available_kinds
    );
  END IF;
END $$;
