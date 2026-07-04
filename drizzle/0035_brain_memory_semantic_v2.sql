CREATE EXTENSION IF NOT EXISTS vector;
--> statement-breakpoint
ALTER TABLE "brain_memory_facts"
  ADD COLUMN IF NOT EXISTS "embedding_v2" vector(384);
--> statement-breakpoint
ALTER TABLE "brain_memory_facts"
  ADD COLUMN IF NOT EXISTS "embedding_v2_model" varchar(96);
--> statement-breakpoint
ALTER TABLE "brain_memory_episodes"
  ADD COLUMN IF NOT EXISTS "embedding_v2" vector(384);
--> statement-breakpoint
ALTER TABLE "brain_memory_episodes"
  ADD COLUMN IF NOT EXISTS "embedding_v2_model" varchar(96);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "brain_memory_facts_embedding_v2_ivfflat_idx"
ON "brain_memory_facts"
USING ivfflat ("embedding_v2" vector_cosine_ops)
WITH (lists = 100);
--> statement-breakpoint
CREATE INDEX IF NOT EXISTS "brain_memory_episodes_embedding_v2_ivfflat_idx"
ON "brain_memory_episodes"
USING ivfflat ("embedding_v2" vector_cosine_ops)
WITH (lists = 100);
