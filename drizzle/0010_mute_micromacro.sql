-- 0007-0009 already contain the social identity, provider plan mapping, and
-- usage backfill changes. Keep this generated migration limited to the one
-- schema delta that was not persisted by those migrations.
ALTER TABLE "training_jobs"
  ADD COLUMN "metadata" jsonb DEFAULT '{}'::jsonb NOT NULL;
