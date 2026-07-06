ALTER TABLE dataset_manifests
  ADD COLUMN IF NOT EXISTS lineage varchar(80) NOT NULL DEFAULT 'legacy',
  ADD COLUMN IF NOT EXISTS privacy_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS quality_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS replay_ratio integer NOT NULL DEFAULT 0 CHECK (replay_ratio BETWEEN 0 AND 100),
  ADD COLUMN IF NOT EXISTS candidate_status varchar(32) NOT NULL DEFAULT 'not_candidate',
  ADD COLUMN IF NOT EXISTS source_window_start timestamptz,
  ADD COLUMN IF NOT EXISTS source_window_end timestamptz;

CREATE INDEX IF NOT EXISTS dataset_manifests_lineage_idx
  ON dataset_manifests (lineage);
CREATE INDEX IF NOT EXISTS dataset_manifests_candidate_status_idx
  ON dataset_manifests (candidate_status);

CREATE TABLE IF NOT EXISTS continuous_learning_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  scope brain_scope NOT NULL DEFAULT 'shared',
  status varchar(32) NOT NULL DEFAULT 'draft',
  window_start timestamptz NOT NULL,
  window_end timestamptz NOT NULL,
  dataset_manifest_id uuid REFERENCES dataset_manifests(id) ON DELETE SET NULL,
  source_event_count integer NOT NULL DEFAULT 0 CHECK (source_event_count >= 0),
  accepted_event_count integer NOT NULL DEFAULT 0 CHECK (accepted_event_count >= 0),
  rejected_event_count integer NOT NULL DEFAULT 0 CHECK (rejected_event_count >= 0),
  deduped_event_count integer NOT NULL DEFAULT 0 CHECK (deduped_event_count >= 0),
  replay_record_count integer NOT NULL DEFAULT 0 CHECK (replay_record_count >= 0),
  train_record_count integer NOT NULL DEFAULT 0 CHECK (train_record_count >= 0),
  validation_record_count integer NOT NULL DEFAULT 0 CHECK (validation_record_count >= 0),
  privacy_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  quality_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  replay_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  promotion_report jsonb NOT NULL DEFAULT '{}'::jsonb,
  config jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT continuous_learning_runs_count_check
    CHECK (source_event_count >= accepted_event_count + rejected_event_count)
);

CREATE INDEX IF NOT EXISTS continuous_learning_runs_owner_idx
  ON continuous_learning_runs (owner_user_id);
CREATE INDEX IF NOT EXISTS continuous_learning_runs_scope_status_idx
  ON continuous_learning_runs (scope, status);
CREATE INDEX IF NOT EXISTS continuous_learning_runs_window_idx
  ON continuous_learning_runs (window_start, window_end);
CREATE INDEX IF NOT EXISTS continuous_learning_runs_dataset_idx
  ON continuous_learning_runs (dataset_manifest_id);

DROP POLICY IF EXISTS continuous_learning_runs_tenant_policy ON continuous_learning_runs;
CREATE POLICY continuous_learning_runs_tenant_policy ON continuous_learning_runs
  USING (
    owner_user_id = elyan_current_user_id()
    OR pg_has_role(current_user, 'elyan_brain_worker', 'member')
  )
  WITH CHECK (
    owner_user_id = elyan_current_user_id()
    OR pg_has_role(current_user, 'elyan_brain_worker', 'member')
  );

-- RLS activation stays in the bootstrap script. Installing this migration alone
-- must not change production behavior while the feature flag is off.
