-- ÖĞRENİLMİŞ DERLEME ŞABLONLARI
--
-- Doğrulanmış epizotlarda tekrar eden adım imzaları buraya aday olarak yazılır.
-- Bir şablon kendiliğinden devreye GİRMEZ: `state` yaşam döngüsünü taşır ve
-- `active` durumuna yalnız gölge + kanarya + manuel yayın sonrası geçer.
CREATE TABLE IF NOT EXISTS "compiled_templates" (
  "id" uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  "template_id" varchar(64) NOT NULL,
  "user_id" uuid NOT NULL REFERENCES "users"("id") ON DELETE CASCADE,
  "intent_family" varchar(120) NOT NULL,
  "contract_digest" varchar(64) NOT NULL,
  "steps" jsonb NOT NULL DEFAULT '[]'::jsonb,
  "state" varchar(16) NOT NULL DEFAULT 'candidate',
  "supporting_episodes" integer NOT NULL DEFAULT 0,
  "fulfilled_episodes" integer NOT NULL DEFAULT 0,
  "consistency" real NOT NULL DEFAULT 0,
  "evidence_kinds" jsonb NOT NULL DEFAULT '[]'::jsonb,
  "median_latency_ms" integer,
  -- Gölge sayaçları: şablon kaç kez eşleşti ve kaç kez dinamik yolun ürettiği
  -- adım dizisiyle AYNI sonucu verdi. Kanaryaya geçiş bu orana bakar.
  "shadow_matches" integer NOT NULL DEFAULT 0,
  "shadow_agreements" integer NOT NULL DEFAULT 0,
  "wrong_execution_count" integer NOT NULL DEFAULT 0,
  "promoted_at" timestamptz,
  "retired_at" timestamptz,
  "retired_reason" varchar(120),
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "updated_at" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "compiled_templates_state_check"
    CHECK ("state" IN ('candidate', 'shadow', 'canary', 'active', 'retired'))
);

CREATE UNIQUE INDEX IF NOT EXISTS "compiled_templates_user_template_uidx"
  ON "compiled_templates" ("user_id", "template_id");
CREATE INDEX IF NOT EXISTS "compiled_templates_lookup_idx"
  ON "compiled_templates" ("user_id", "intent_family", "state");
