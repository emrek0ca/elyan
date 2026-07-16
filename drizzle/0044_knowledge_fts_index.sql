-- Keyword RAG (BM25 sınıfı) için full-text GIN indeksi.
-- retrieval-orchestrator.ts turkish config ile arar, simple'a düşer;
-- indeks turkish üzerine kurulur (sorgu indeksi kullanamadığında da doğru
-- çalışır, yalnızca yavaşlar).
CREATE INDEX IF NOT EXISTS knowledge_chunks_fts_turkish_idx
  ON knowledge_chunks
  USING gin (to_tsvector('turkish'::regconfig, coalesce(content, '')));
