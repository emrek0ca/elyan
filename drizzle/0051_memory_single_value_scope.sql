DROP INDEX IF EXISTS "brain_memory_facts_single_value_active_uidx";

CREATE UNIQUE INDEX IF NOT EXISTS "brain_memory_facts_single_value_active_uidx"
  ON "brain_memory_facts" ("user_id", "canonical_key", "fact_type")
  WHERE
    "conflict_status" = 'active'
    AND "lifecycle_status" = 'active'
    AND "deleted_at" IS NULL
    AND "canonical_key" IN (
      'name',
      'preferred_name',
      'preferred_language',
      'preferred_tone',
      'response_style_preference',
      'timezone',
      'job_title',
      'company',
      'location',
      'project',
      'active_project',
      'primary_repo',
      'working_boundary',
      'implementation_boundary'
    );
