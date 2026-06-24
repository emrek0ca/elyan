ALTER TABLE "brain_memory_episodes"
ADD COLUMN "is_pinned" boolean DEFAULT false NOT NULL,
ADD COLUMN "lifecycle_status" varchar(32) DEFAULT 'active' NOT NULL,
ADD COLUMN "deleted_at" timestamp with time zone,
ADD COLUMN "deleted_reason" varchar(240);

ALTER TABLE "brain_memory_facts"
ADD COLUMN "lifecycle_status" varchar(32) DEFAULT 'active' NOT NULL,
ADD COLUMN "deleted_at" timestamp with time zone,
ADD COLUMN "deleted_reason" varchar(240);

UPDATE "brain_memory_episodes"
SET "lifecycle_status" = CASE
  WHEN "deleted_at" IS NOT NULL THEN 'soft_deleted'
  WHEN "stale_at" IS NOT NULL THEN 'stale'
  ELSE 'active'
END;

UPDATE "brain_memory_facts"
SET "lifecycle_status" = CASE
  WHEN "deleted_at" IS NOT NULL THEN 'soft_deleted'
  WHEN "conflict_status" = 'superseded' THEN 'superseded'
  WHEN "conflict_status" = 'contested' THEN 'contested'
  WHEN "stale_at" IS NOT NULL THEN 'stale'
  ELSE 'active'
END;

CREATE INDEX "brain_memory_episodes_pinned_idx" ON "brain_memory_episodes" USING btree ("is_pinned");
CREATE INDEX "brain_memory_episodes_lifecycle_idx" ON "brain_memory_episodes" USING btree ("lifecycle_status");
CREATE INDEX "brain_memory_facts_lifecycle_idx" ON "brain_memory_facts" USING btree ("lifecycle_status");
