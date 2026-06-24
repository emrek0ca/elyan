CREATE EXTENSION IF NOT EXISTS vector;
--> statement-breakpoint

ALTER TABLE "knowledge_chunks"
ADD COLUMN IF NOT EXISTS "embedding" vector(256);
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "knowledge_chunks_embedding_ivfflat_idx"
ON "knowledge_chunks"
USING ivfflat ("embedding" vector_cosine_ops)
WITH (lists = 100);
