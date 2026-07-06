-- Maintenance-window migration. It preserves public table names but takes
-- ACCESS EXCLUSIVE locks during the final copy/cutover.
BEGIN;

LOCK TABLE learning_events, turn_metrics, task_events IN ACCESS EXCLUSIVE MODE;

CREATE TABLE learning_events_partitioned
  (LIKE learning_events INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY INCLUDING STORAGE)
  PARTITION BY RANGE (created_at);
CREATE TABLE turn_metrics_partitioned
  (LIKE turn_metrics INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY INCLUDING STORAGE)
  PARTITION BY RANGE (created_at);
CREATE TABLE task_events_partitioned
  (LIKE task_events INCLUDING DEFAULTS INCLUDING GENERATED INCLUDING IDENTITY INCLUDING STORAGE)
  PARTITION BY RANGE (created_at);

DO $$
DECLARE
  month_start date;
  month_end date;
  suffix text;
  parent_name text;
  child_prefix text;
  bucket integer;
  hash_parent_name text;
BEGIN
  FOREACH parent_name IN ARRAY ARRAY[
    'learning_events_partitioned',
    'turn_metrics_partitioned',
    'task_events_partitioned'
  ] LOOP
    child_prefix := replace(parent_name, '_partitioned', '');
    FOR month_start IN
      SELECT generate_series(
        date_trunc('month', now()) - interval '24 months',
        date_trunc('month', now()) + interval '12 months',
        interval '1 month'
      )::date
    LOOP
      month_end := (month_start + interval '1 month')::date;
      suffix := to_char(month_start, 'YYYYMM');
      IF parent_name IN ('learning_events_partitioned', 'turn_metrics_partitioned') THEN
        hash_parent_name := child_prefix || '_p' || suffix;
        EXECUTE format(
          'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L) PARTITION BY HASH (user_id)',
          hash_parent_name,
          parent_name,
          month_start,
          month_end
        );
        FOR bucket IN 0..15 LOOP
          EXECUTE format(
            'CREATE TABLE %I PARTITION OF %I FOR VALUES WITH (MODULUS 16, REMAINDER %s)',
            hash_parent_name || '_h' || lpad(bucket::text, 2, '0'),
            hash_parent_name,
            bucket
          );
        END LOOP;
      ELSE
        EXECUTE format(
          'CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
          child_prefix || '_p' || suffix,
          parent_name,
          month_start,
          month_end
        );
      END IF;
    END LOOP;
    EXECUTE format(
      'CREATE TABLE %I PARTITION OF %I DEFAULT',
      child_prefix || '_default',
      parent_name
    );
  END LOOP;
END $$;

INSERT INTO learning_events_partitioned SELECT * FROM learning_events;
INSERT INTO turn_metrics_partitioned SELECT * FROM turn_metrics;
INSERT INTO task_events_partitioned SELECT * FROM task_events;

ALTER TABLE learning_events RENAME TO learning_events_unpartitioned;
ALTER TABLE turn_metrics RENAME TO turn_metrics_unpartitioned;
ALTER TABLE task_events RENAME TO task_events_unpartitioned;
ALTER TABLE learning_events_partitioned RENAME TO learning_events;
ALTER TABLE turn_metrics_partitioned RENAME TO turn_metrics;
ALTER TABLE task_events_partitioned RENAME TO task_events;

DROP TABLE learning_events_unpartitioned;
DROP TABLE turn_metrics_unpartitioned;
DROP TABLE task_events_unpartitioned;

ALTER TABLE learning_events ADD PRIMARY KEY (id, created_at);
ALTER TABLE learning_events
  ADD CONSTRAINT learning_events_user_id_users_id_fk
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE learning_events
  ADD CONSTRAINT learning_events_task_id_tasks_id_fk
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL;
CREATE INDEX learning_events_user_idx ON learning_events (user_id, created_at DESC);
CREATE INDEX learning_events_lookup_idx ON learning_events (user_id, scope, type, key, created_at DESC);
CREATE INDEX learning_events_expires_idx ON learning_events (expires_at) WHERE expires_at IS NOT NULL;

ALTER TABLE turn_metrics ADD PRIMARY KEY (turn_id, created_at);
ALTER TABLE turn_metrics
  ADD CONSTRAINT turn_metrics_user_id_users_id_fk
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
ALTER TABLE turn_metrics
  ADD CONSTRAINT turn_metrics_session_id_chat_sessions_id_fk
  FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL;
CREATE INDEX turn_metrics_user_created_idx ON turn_metrics (user_id, created_at DESC);
CREATE INDEX turn_metrics_session_created_idx ON turn_metrics (session_id, created_at DESC);
CREATE INDEX turn_metrics_workload_created_idx ON turn_metrics (workload, created_at DESC);

ALTER TABLE task_events ADD PRIMARY KEY (id, created_at);
ALTER TABLE task_events
  ADD CONSTRAINT task_events_task_id_tasks_id_fk
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE;
ALTER TABLE task_events
  ADD CONSTRAINT task_events_payload_blob_id_blob_objects_id_fk
  FOREIGN KEY (payload_blob_id) REFERENCES blob_objects(id) ON DELETE SET NULL;
CREATE INDEX task_events_task_idx ON task_events (task_id, created_at DESC);

CREATE OR REPLACE FUNCTION elyan_ensure_event_partitions(months_ahead integer DEFAULT 3)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
  month_start date;
  month_end date;
  suffix text;
  parent_name text;
  bucket integer;
  partition_name text;
BEGIN
  IF months_ahead < 1 OR months_ahead > 24 THEN
    RAISE EXCEPTION 'months_ahead must be between 1 and 24';
  END IF;
  FOREACH parent_name IN ARRAY ARRAY['learning_events', 'turn_metrics', 'task_events'] LOOP
    FOR month_start IN
      SELECT generate_series(
        date_trunc('month', now()),
        date_trunc('month', now()) + make_interval(months => months_ahead),
        interval '1 month'
      )::date
    LOOP
      month_end := (month_start + interval '1 month')::date;
      suffix := to_char(month_start, 'YYYYMM');
      partition_name := parent_name || '_p' || suffix;
      IF parent_name IN ('learning_events', 'turn_metrics') THEN
        EXECUTE format(
          'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L) PARTITION BY HASH (user_id)',
          partition_name,
          parent_name,
          month_start,
          month_end
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
      ELSE
        EXECUTE format(
          'CREATE TABLE IF NOT EXISTS %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
          partition_name,
          parent_name,
          month_start,
          month_end
        );
      END IF;
    END LOOP;
  END LOOP;
END $$;

COMMIT;
