-- TİPLİ EPİZOT AMBARI
--
-- Deneyim şimdiye kadar `learning_events` içinde düz bir metin satırıydı;
-- geri çağırma metin eşlemesine düşüyordu. Bu tablo epizotu tipler ve
-- `request_embedding` üzerinden semantik komşulukla çağrılabilir yapar.
--
-- Ham istek metni saklanmaz: yalnız özet, uzunluk kovası, dil ve türev gömme.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS "task_episodes" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
  "task_id" uuid REFERENCES "tasks"("id") ON DELETE SET NULL,
  "episode_id" varchar(120) NOT NULL,
  "turn_id" varchar(160),
  "request_sha256" varchar(64),
  "request_length_bucket" varchar(24),
  "language" varchar(16),
  "request_embedding" vector(384),
  "embedding_model" varchar(96),
  "intent_family" varchar(120) NOT NULL DEFAULT 'unknown',
  "route" varchar(64),
  "mode" varchar(16),
  "contract_digest" varchar(64),
  "step_shapes" jsonb NOT NULL DEFAULT '[]'::jsonb,
  "outcome_verdict" varchar(16) NOT NULL,
  "verification_evidence" jsonb NOT NULL DEFAULT '[]'::jsonb,
  "latency_ms" integer,
  "model_calls" integer,
  "repair_attempts" integer,
  "training_eligible" boolean NOT NULL DEFAULT false,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "task_episodes_verdict_check"
    CHECK ("outcome_verdict" IN ('fulfilled', 'degraded', 'unfulfilled')),
  CONSTRAINT "task_episodes_mode_check"
    CHECK ("mode" IS NULL OR "mode" IN ('compiled', 'dynamic'))
);

CREATE UNIQUE INDEX IF NOT EXISTS "task_episodes_episode_uidx"
  ON "task_episodes" ("episode_id");
CREATE INDEX IF NOT EXISTS "task_episodes_user_intent_idx"
  ON "task_episodes" ("user_id", "intent_family", "created_at");
-- Şablon sentezi bu indeksten okur: aynı ailede aynı adım imzasının kaç kez
-- ve hangi sonuçla tekrarlandığı tek taramada çıkmalı.
CREATE INDEX IF NOT EXISTS "task_episodes_digest_idx"
  ON "task_episodes" ("intent_family", "contract_digest", "outcome_verdict");
CREATE INDEX IF NOT EXISTS "task_episodes_created_idx"
  ON "task_episodes" ("created_at");

-- ivfflat, mevcut brain_memory_* indeksleriyle aynı kip; liste sayısı küçük
-- başlar çünkü tablo boş doğar ve ivfflat boş tabloda eğitilemez.
CREATE INDEX IF NOT EXISTS "task_episodes_request_embedding_ivfflat_idx"
  ON "task_episodes"
  USING ivfflat ("request_embedding" vector_cosine_ops)
  WITH (lists = 50);
