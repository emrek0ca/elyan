UPDATE "brain_memory_facts"
SET
  "canonical_key" = 'preferred_name',
  "key" = 'preferred_name'
WHERE "canonical_key" IN (
  'address_name',
  'form_of_address',
  'hitap_adı',
  'hitap_adi',
  'hitap_şekli',
  'hitap_sekli',
  'preferred_address',
  'preferred_address_name'
);

WITH ranked AS (
  SELECT
    "id",
    row_number() OVER (
      PARTITION BY "user_id", "canonical_key", "fact_type"
      ORDER BY "updated_at" DESC, "id" DESC
    ) AS active_rank
  FROM "brain_memory_facts"
  WHERE "conflict_status" = 'active'
    AND "lifecycle_status" = 'active'
    AND "deleted_at" IS NULL
    AND "canonical_key" IN (
      'name',
      'preferred_name',
      'preferred_language',
      'preferred_tone',
      'response_style_preference',
      'timezone'
    )
)
UPDATE "brain_memory_facts" AS facts
SET
  "conflict_status" = 'superseded',
  "lifecycle_status" = 'superseded',
  "stale_at" = now(),
  "updated_at" = now()
FROM ranked
WHERE facts."id" = ranked."id"
  AND ranked.active_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS "brain_memory_facts_single_value_active_uidx"
  ON "brain_memory_facts" ("user_id", "canonical_key", "fact_type")
  WHERE "conflict_status" = 'active'
    AND "lifecycle_status" = 'active'
    AND "deleted_at" IS NULL
    AND "canonical_key" IN (
      'name',
      'preferred_name',
      'preferred_language',
      'preferred_tone',
      'response_style_preference',
      'timezone'
    );
