CREATE UNIQUE INDEX IF NOT EXISTS tasks_id_user_uidx ON tasks (id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS session_goals_id_user_uidx ON session_goals (id, user_id);

CREATE TABLE IF NOT EXISTS agent_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  task_id uuid NOT NULL UNIQUE REFERENCES tasks(id) ON DELETE CASCADE,
  session_id uuid REFERENCES chat_sessions(id) ON DELETE SET NULL,
  goal_id uuid REFERENCES session_goals(id) ON DELETE SET NULL,
  state varchar(32) NOT NULL DEFAULT 'understanding',
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  plan jsonb NOT NULL DEFAULT '{}'::jsonb,
  max_steps integer NOT NULL DEFAULT 8 CHECK (max_steps BETWEEN 1 AND 8),
  max_tool_calls integer NOT NULL DEFAULT 12 CHECK (max_tool_calls BETWEEN 1 AND 12),
  max_replans integer NOT NULL DEFAULT 2 CHECK (max_replans BETWEEN 0 AND 2),
  tool_call_count integer NOT NULL DEFAULT 0 CHECK (tool_call_count >= 0),
  replan_count integer NOT NULL DEFAULT 0 CHECK (replan_count >= 0),
  active_compute_ms integer NOT NULL DEFAULT 0 CHECK (active_compute_ms >= 0),
  active_compute_budget_ms integer NOT NULL DEFAULT 120000 CHECK (active_compute_budget_ms > 0),
  lease_owner varchar(160),
  lease_expires_at timestamptz,
  waiting_expires_at timestamptz,
  terminal_result jsonb,
  failure_code varchar(96),
  shadow boolean NOT NULL DEFAULT false,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, user_id),
  CONSTRAINT agent_runs_task_user_fk FOREIGN KEY (task_id, user_id)
    REFERENCES tasks(id, user_id) ON DELETE CASCADE,
  CONSTRAINT agent_runs_session_user_fk FOREIGN KEY (session_id, user_id)
    REFERENCES chat_sessions(id, user_id) ON DELETE SET NULL,
  CONSTRAINT agent_runs_goal_user_fk FOREIGN KEY (goal_id, user_id)
    REFERENCES session_goals(id, user_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS agent_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  step_key varchar(80) NOT NULL,
  sequence integer NOT NULL CHECK (sequence >= 0),
  state varchar(32) NOT NULL DEFAULT 'pending',
  depends_on jsonb NOT NULL DEFAULT '[]'::jsonb,
  expected_outcome jsonb NOT NULL DEFAULT '{}'::jsonb,
  tool_request jsonb NOT NULL DEFAULT '{}'::jsonb,
  tool_result jsonb,
  verification jsonb,
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 3),
  idempotency_key varchar(160) NOT NULL UNIQUE,
  started_at timestamptz,
  observed_at timestamptz,
  verified_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, step_key),
  UNIQUE (id, user_id),
  CONSTRAINT agent_steps_run_user_fk FOREIGN KEY (run_id, user_id)
    REFERENCES agent_runs(id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  step_id uuid NOT NULL REFERENCES agent_steps(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind varchar(32) NOT NULL CHECK (kind IN ('tool_result', 'artifact', 'state_readback')),
  source_ref varchar(200),
  content_hash varchar(64),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  valid boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_evidence_step_user_fk FOREIGN KEY (step_id, user_id)
    REFERENCES agent_steps(id, user_id) ON DELETE CASCADE,
  CONSTRAINT agent_evidence_run_user_fk FOREIGN KEY (run_id, user_id)
    REFERENCES agent_runs(id, user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS agent_events (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  step_id uuid REFERENCES agent_steps(id) ON DELETE SET NULL,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  revision integer NOT NULL,
  event_type varchar(64) NOT NULL,
  from_state varchar(32),
  to_state varchar(32) NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, created_at, user_id),
  CONSTRAINT agent_events_run_user_fk FOREIGN KEY (run_id, user_id)
    REFERENCES agent_runs(id, user_id) ON DELETE CASCADE
) PARTITION BY RANGE (created_at);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'agent_events'::regclass
      AND conname = 'agent_events_pkey'
      AND contype = 'p'
  ) AND NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN unnest(c.conkey) AS key(attnum) ON true
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = key.attnum
    WHERE c.conrelid = 'agent_events'::regclass
      AND c.conname = 'agent_events_pkey'
      AND a.attname = 'user_id'
  ) THEN
    ALTER TABLE agent_events DROP CONSTRAINT agent_events_pkey;
    ALTER TABLE agent_events ADD PRIMARY KEY (id, created_at, user_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS agent_events_default PARTITION OF agent_events DEFAULT;

CREATE INDEX IF NOT EXISTS agent_runs_user_state_idx ON agent_runs (user_id, state, updated_at);
CREATE INDEX IF NOT EXISTS agent_runs_lease_idx ON agent_runs (state, lease_expires_at);
CREATE INDEX IF NOT EXISTS agent_steps_run_state_idx ON agent_steps (run_id, state, sequence);
CREATE INDEX IF NOT EXISTS agent_evidence_step_idx ON agent_evidence (step_id, created_at);
CREATE INDEX IF NOT EXISTS agent_evidence_run_idx ON agent_evidence (run_id, created_at);
CREATE INDEX IF NOT EXISTS agent_events_run_revision_idx ON agent_events (run_id, revision, created_at);
CREATE INDEX IF NOT EXISTS agent_events_user_created_idx ON agent_events (user_id, created_at);

DROP POLICY IF EXISTS agent_runs_tenant_policy ON agent_runs;
CREATE POLICY agent_runs_tenant_policy ON agent_runs
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));
DROP POLICY IF EXISTS agent_steps_tenant_policy ON agent_steps;
CREATE POLICY agent_steps_tenant_policy ON agent_steps
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));
DROP POLICY IF EXISTS agent_evidence_tenant_policy ON agent_evidence;
CREATE POLICY agent_evidence_tenant_policy ON agent_evidence
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));
DROP POLICY IF EXISTS agent_events_tenant_policy ON agent_events;
CREATE POLICY agent_events_tenant_policy ON agent_events
  USING (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'))
  WITH CHECK (user_id = elyan_current_user_id() OR pg_has_role(current_user, 'elyan_brain_worker', 'member'));

CREATE OR REPLACE FUNCTION elyan_ensure_agent_event_partitions(reference_month date DEFAULT CURRENT_DATE)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
  month_start date;
  month_end date;
  partition_name text;
  bucket integer;
BEGIN
  FOR offset_month IN -1..12 LOOP
    month_start := (date_trunc('month', reference_month)::date + (offset_month || ' months')::interval)::date;
    month_end := (month_start + interval '1 month')::date;
    partition_name := 'agent_events_' || to_char(month_start, 'YYYY_MM');
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF agent_events FOR VALUES FROM (%L) TO (%L) PARTITION BY HASH (user_id)',
      partition_name, month_start, month_end
    );
    IF EXISTS (
      SELECT 1 FROM pg_partitioned_table WHERE partrelid = to_regclass(partition_name)
    ) THEN
      FOR bucket IN 0..15 LOOP
        EXECUTE format(
          'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES WITH (MODULUS 16, REMAINDER %s)',
          partition_name || '_h' || lpad(bucket::text, 2, '0'),
          partition_name,
          bucket
        );
      END LOOP;
    END IF;
  END LOOP;
END $$;

SELECT elyan_ensure_agent_event_partitions(CURRENT_DATE);
