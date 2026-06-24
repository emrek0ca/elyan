ALTER TABLE "runtime_connections"
ADD COLUMN "capability_states" jsonb NOT NULL DEFAULT '{}'::jsonb;
