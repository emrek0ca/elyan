/**
 * Canonical hosted control-plane migration list and schema verification helpers.
 * Layer: database + control-plane. Critical for schema initialization and drift detection.
 */
import type { Pool, QueryResultRow } from 'pg';
import { ControlPlaneConfigurationError } from './errors';

export type ControlPlaneMigration = {
  version: number;
  name: string;
  sql: string;
};

export const controlPlaneMigrations: ControlPlaneMigration[] = [
  {
    version: 1,
    name: 'initial_schema',
    sql: `
      CREATE EXTENSION IF NOT EXISTS pgcrypto;

      CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY DEFAULT ('usr_' || replace(gen_random_uuid()::text, '-', '')),
        name TEXT,
        email TEXT UNIQUE NOT NULL,
        "emailVerified" TIMESTAMPTZ,
        image TEXT
      );

      CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY DEFAULT ('acc_' || replace(gen_random_uuid()::text, '-', '')),
        "userId" TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        provider TEXT NOT NULL,
        type TEXT NOT NULL,
        "providerAccountId" TEXT NOT NULL,
        access_token TEXT,
        expires_at INTEGER,
        refresh_token TEXT,
        id_token TEXT,
        scope TEXT,
        session_state TEXT,
        token_type TEXT
      );

      CREATE UNIQUE INDEX IF NOT EXISTS accounts_provider_account_idx
        ON accounts (provider, "providerAccountId");

      CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY DEFAULT ('ses_' || replace(gen_random_uuid()::text, '-', '')),
        "sessionToken" TEXT UNIQUE NOT NULL,
        "userId" TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires TIMESTAMPTZ NOT NULL
      );

      CREATE TABLE IF NOT EXISTS verification_token (
        identifier TEXT NOT NULL,
        token TEXT NOT NULL,
        expires TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (identifier, token)
      );

      CREATE TABLE IF NOT EXISTS elyan_accounts (
        account_id TEXT PRIMARY KEY,
        owner_user_id TEXT,
        display_name TEXT NOT NULL,
        owner_type TEXT NOT NULL,
        billing_customer_ref TEXT,
        status TEXT NOT NULL,
        balance_credits NUMERIC(18, 2) NOT NULL,
        usage_totals JSONB NOT NULL DEFAULT '{}'::jsonb,
        interaction_state JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
      );

      CREATE TABLE IF NOT EXISTS elyan_subscriptions (
        account_id TEXT PRIMARY KEY REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        plan_id TEXT NOT NULL,
        status TEXT NOT NULL,
        provider TEXT NOT NULL,
        provider_customer_ref TEXT,
        provider_product_ref TEXT,
        provider_pricing_plan_ref TEXT,
        provider_subscription_ref TEXT,
        provider_status TEXT,
        sync_state TEXT NOT NULL,
        retry_count INTEGER NOT NULL DEFAULT 0,
        last_synced_at TIMESTAMPTZ,
        next_retry_at TIMESTAMPTZ,
        last_sync_error TEXT,
        current_period_started_at TIMESTAMPTZ NOT NULL,
        current_period_ends_at TIMESTAMPTZ NOT NULL,
        credits_granted_this_period NUMERIC(18, 2) NOT NULL
      );

      CREATE TABLE IF NOT EXISTS elyan_users (
        user_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        email TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL,
        owner_type TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'owner',
        password_salt TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        last_login_at TIMESTAMPTZ
      );

      CREATE TABLE IF NOT EXISTS elyan_ledger_entries (
        entry_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        status TEXT NOT NULL,
        domain TEXT,
        credits_delta NUMERIC(18, 2) NOT NULL,
        balance_after NUMERIC(18, 2) NOT NULL,
        source TEXT,
        request_id TEXT,
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL
      );

      CREATE TABLE IF NOT EXISTS elyan_billing_plan_bindings (
        provider TEXT NOT NULL,
        plan_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        product_reference_code TEXT,
        pricing_plan_name TEXT NOT NULL,
        pricing_plan_reference_code TEXT,
        currency_code TEXT NOT NULL,
        payment_interval TEXT NOT NULL,
        payment_interval_count INTEGER NOT NULL,
        plan_payment_type TEXT NOT NULL,
        sync_state TEXT NOT NULL,
        last_synced_at TIMESTAMPTZ,
        last_sync_error TEXT,
        PRIMARY KEY (provider, plan_id)
      );

      CREATE TABLE IF NOT EXISTS elyan_status_events (
        event_id BIGSERIAL PRIMARY KEY,
        account_id TEXT REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        event_type TEXT NOT NULL,
        previous_state JSONB,
        next_state JSONB,
        note TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );

      CREATE TABLE IF NOT EXISTS elyan_notifications (
        notification_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        kind TEXT NOT NULL,
        level TEXT NOT NULL,
        seen_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL
      );

      CREATE TABLE IF NOT EXISTS elyan_device_links (
        link_code TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES elyan_users(user_id) ON DELETE CASCADE,
        device_label TEXT NOT NULL,
        status TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        completed_at TIMESTAMPTZ,
        consumed_at TIMESTAMPTZ,
        device_token TEXT
      );

      CREATE TABLE IF NOT EXISTS elyan_devices (
        device_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES elyan_users(user_id) ON DELETE CASCADE,
        device_label TEXT NOT NULL,
        status TEXT NOT NULL,
        device_token TEXT UNIQUE NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        last_seen_release_tag TEXT,
        last_seen_at TIMESTAMPTZ,
        linked_at TIMESTAMPTZ NOT NULL,
        revoked_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
      );

      CREATE UNIQUE INDEX IF NOT EXISTS elyan_devices_device_token_idx
        ON elyan_devices (device_token);

      CREATE TABLE IF NOT EXISTS elyan_integrations (
        integration_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        provider TEXT NOT NULL,
        display_name TEXT NOT NULL,
        status TEXT NOT NULL,
        scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
        surfaces JSONB NOT NULL DEFAULT '[]'::jsonb,
        external_account_id TEXT,
        external_account_label TEXT,
        access_token_ciphertext TEXT,
        refresh_token_ciphertext TEXT,
        id_token_ciphertext TEXT,
        expires_at TIMESTAMPTZ,
        last_synced_at TIMESTAMPTZ,
        last_error TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
      );

      CREATE UNIQUE INDEX IF NOT EXISTS elyan_integrations_account_provider_idx
        ON elyan_integrations (account_id, provider);

      CREATE INDEX IF NOT EXISTS elyan_integrations_account_status_idx
        ON elyan_integrations (account_id, status);
    `,
  },
  {
    version: 2,
    name: 'evaluation_signals',
    sql: `
      CREATE TABLE IF NOT EXISTS elyan_evaluation_signals (
        signal_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        request_id TEXT,
        payload JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
      );

      CREATE INDEX IF NOT EXISTS elyan_evaluation_signals_account_created_idx
        ON elyan_evaluation_signals (account_id, created_at DESC);

      CREATE INDEX IF NOT EXISTS elyan_evaluation_signals_request_idx
        ON elyan_evaluation_signals (request_id);
    `,
  },
  {
    version: 3,
    name: 'subscription_webhook_idempotency',
    sql: `
      ALTER TABLE elyan_subscriptions
        ADD COLUMN IF NOT EXISTS processed_webhook_event_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
    `,
  },
  {
    version: 4,
    name: 'account_usage_snapshot',
    sql: `
      ALTER TABLE elyan_accounts
        ADD COLUMN IF NOT EXISTS usage_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb;
    `,
  },
  {
    version: 5,
    name: 'interaction_state',
    sql: `
      ALTER TABLE elyan_accounts
        ADD COLUMN IF NOT EXISTS interaction_state JSONB NOT NULL DEFAULT '{}'::jsonb;
    `,
  },
  {
    version: 6,
    name: 'integrations',
    sql: `
      CREATE TABLE IF NOT EXISTS elyan_integrations (
        integration_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        provider TEXT NOT NULL,
        display_name TEXT NOT NULL,
        status TEXT NOT NULL,
        scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
        surfaces JSONB NOT NULL DEFAULT '[]'::jsonb,
        external_account_id TEXT,
        external_account_label TEXT,
        access_token_ciphertext TEXT,
        refresh_token_ciphertext TEXT,
        id_token_ciphertext TEXT,
        expires_at TIMESTAMPTZ,
        last_synced_at TIMESTAMPTZ,
        last_error TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
      );

      CREATE UNIQUE INDEX IF NOT EXISTS elyan_integrations_account_provider_idx
        ON elyan_integrations (account_id, provider);

      CREATE INDEX IF NOT EXISTS elyan_integrations_account_status_idx
        ON elyan_integrations (account_id, status);
    `,
  },
  {
    version: 7,
    name: 'canonical_shared_truth_relations',
    sql: `
      CREATE OR REPLACE VIEW subscriptions AS
        SELECT
          account_id,
          plan_id,
          status,
          provider,
          provider_customer_ref,
          provider_product_ref,
          provider_pricing_plan_ref,
          provider_subscription_ref,
          provider_status,
          sync_state,
          retry_count,
          last_synced_at,
          next_retry_at,
          last_sync_error,
          current_period_started_at,
          current_period_ends_at,
          credits_granted_this_period,
          processed_webhook_event_refs
        FROM elyan_subscriptions;

      CREATE OR REPLACE VIEW entitlements AS
        SELECT
          account.account_id,
          subscription.plan_id,
          subscription.status AS subscription_status,
          subscription.sync_state,
          (
            subscription.sync_state = 'synced'
            AND subscription.status IN ('active', 'trialing')
            AND subscription.plan_id <> 'free'
          ) AS hosted_access,
          (
            subscription.sync_state = 'synced'
            AND subscription.status IN ('active', 'trialing')
            AND subscription.plan_id <> 'free'
          ) AS hosted_usage_accounting,
          account.updated_at
        FROM elyan_accounts account
        JOIN elyan_subscriptions subscription ON subscription.account_id = account.account_id;

      CREATE OR REPLACE VIEW token_ledger AS
        SELECT
          entry_id,
          account_id,
          kind,
          status,
          domain,
          credits_delta,
          balance_after,
          source,
          request_id,
          note,
          created_at
        FROM elyan_ledger_entries;

      CREATE OR REPLACE VIEW usage_counters AS
        SELECT
          account_id,
          usage_totals,
          usage_snapshot,
          updated_at
        FROM elyan_accounts;

      CREATE OR REPLACE VIEW usage_events AS
        SELECT
          event_id,
          account_id,
          event_type,
          previous_state,
          next_state,
          note,
          created_at
        FROM elyan_status_events;

      CREATE OR REPLACE VIEW billing_profiles AS
        SELECT
          account_id,
          billing_customer_ref,
          balance_credits,
          usage_totals,
          usage_snapshot,
          created_at,
          updated_at
        FROM elyan_accounts;

      CREATE OR REPLACE VIEW notifications AS
        SELECT
          notification_id,
          account_id,
          title,
          body,
          kind,
          level,
          seen_at,
          created_at
        FROM elyan_notifications;

      CREATE OR REPLACE VIEW device_link_requests AS
        SELECT
          link_code,
          account_id,
          user_id,
          device_label,
          status,
          expires_at,
          created_at,
          completed_at,
          consumed_at,
          device_token
        FROM elyan_device_links;

      CREATE OR REPLACE VIEW devices AS
        SELECT
          device_id,
          account_id,
          user_id,
          device_label,
          status,
          metadata,
          last_seen_release_tag,
          last_seen_at,
          linked_at,
          revoked_at,
          created_at,
          updated_at
        FROM elyan_devices;

      CREATE TABLE IF NOT EXISTS release_cache (
        repository TEXT PRIMARY KEY,
        tag_name TEXT,
        payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        refreshed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
    `,
  },
  {
    version: 8,
    name: 'learning_events',
    sql: `
      CREATE EXTENSION IF NOT EXISTS pgcrypto;

      CREATE TABLE IF NOT EXISTS learning_events (
        event_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        request_id TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL,
        input TEXT NOT NULL,
        intent TEXT NOT NULL,
        plan TEXT NOT NULL,
        reasoning_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
        output TEXT NOT NULL DEFAULT '',
        success BOOLEAN NOT NULL,
        failure_reason TEXT,
        latency_ms INTEGER NOT NULL,
        score NUMERIC(4, 2) NOT NULL,
        model_id TEXT,
        model_provider TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );

      ALTER TABLE learning_events
        ADD COLUMN IF NOT EXISTS event_id TEXT,
        ADD COLUMN IF NOT EXISTS account_id TEXT REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        ADD COLUMN IF NOT EXISTS request_id TEXT,
        ADD COLUMN IF NOT EXISTS source TEXT,
        ADD COLUMN IF NOT EXISTS intent TEXT,
        ADD COLUMN IF NOT EXISTS plan TEXT,
        ADD COLUMN IF NOT EXISTS reasoning_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
        ADD COLUMN IF NOT EXISTS success BOOLEAN,
        ADD COLUMN IF NOT EXISTS failure_reason TEXT,
        ADD COLUMN IF NOT EXISTS latency_ms INTEGER,
        ADD COLUMN IF NOT EXISTS model_id TEXT,
        ADD COLUMN IF NOT EXISTS model_provider TEXT,
        ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1
          FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name = 'learning_events'
            AND column_name = 'id'
        ) THEN
          EXECUTE 'UPDATE learning_events SET event_id = COALESCE(event_id, id::text) WHERE event_id IS NULL';
        END IF;
      END $$;

      UPDATE learning_events
      SET event_id = COALESCE(event_id, 'evt_' || encode(digest(coalesce(input, '') || coalesce(output, '') || coalesce(created_at::text, ''), 'sha256'), 'hex')),
          request_id = COALESCE(request_id, event_id),
          source = COALESCE(NULLIF(source, ''), 'web'),
          input = COALESCE(input, ''),
          intent = COALESCE(NULLIF(intent, ''), 'unknown'),
          plan = COALESCE(NULLIF(plan, ''), 'legacy'),
          output = COALESCE(output, ''),
          success = COALESCE(success, true),
          latency_ms = COALESCE(latency_ms, 0),
          score = COALESCE(score, 0),
          metadata = COALESCE(metadata, '{}'::jsonb),
          updated_at = COALESCE(updated_at, NOW());

      ALTER TABLE learning_events
        ALTER COLUMN event_id SET NOT NULL,
        ALTER COLUMN request_id SET NOT NULL,
        ALTER COLUMN source SET NOT NULL,
        ALTER COLUMN input SET NOT NULL,
        ALTER COLUMN intent SET NOT NULL,
        ALTER COLUMN plan SET NOT NULL,
        ALTER COLUMN reasoning_steps SET NOT NULL,
        ALTER COLUMN output SET NOT NULL,
        ALTER COLUMN success SET NOT NULL,
        ALTER COLUMN latency_ms SET NOT NULL,
        ALTER COLUMN score SET NOT NULL,
        ALTER COLUMN metadata SET NOT NULL,
        ALTER COLUMN updated_at SET NOT NULL;

      CREATE UNIQUE INDEX IF NOT EXISTS learning_events_event_id_idx
        ON learning_events (event_id);

      CREATE UNIQUE INDEX IF NOT EXISTS learning_events_request_id_idx
        ON learning_events (request_id);

      CREATE INDEX IF NOT EXISTS learning_events_account_created_idx
        ON learning_events (account_id, created_at DESC);

      CREATE INDEX IF NOT EXISTS learning_events_created_idx
        ON learning_events (created_at DESC);
    `,
  },
  {
    version: 9,
    name: 'model_artifacts',
    sql: `
      CREATE EXTENSION IF NOT EXISTS pgcrypto;

      CREATE TABLE IF NOT EXISTS model_artifacts (
        model_version TEXT PRIMARY KEY,
        base_model TEXT NOT NULL,
        dataset_size INTEGER NOT NULL,
        loss NUMERIC(10, 6),
        score NUMERIC(10, 6),
        active BOOLEAN NOT NULL DEFAULT false,
        artifact_path TEXT NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );

      ALTER TABLE model_artifacts
        ADD COLUMN IF NOT EXISTS model_version TEXT,
        ADD COLUMN IF NOT EXISTS base_model TEXT,
        ADD COLUMN IF NOT EXISTS dataset_size INTEGER,
        ADD COLUMN IF NOT EXISTS loss NUMERIC(10, 6),
        ADD COLUMN IF NOT EXISTS score NUMERIC(10, 6),
        ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT false,
        ADD COLUMN IF NOT EXISTS artifact_path TEXT,
        ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1
          FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name = 'model_artifacts'
            AND column_name = 'version'
        ) THEN
          EXECUTE 'UPDATE model_artifacts SET model_version = COALESCE(model_version, version::text) WHERE model_version IS NULL';
        END IF;

        IF EXISTS (
          SELECT 1
          FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name = 'model_artifacts'
            AND column_name = 'path'
        ) THEN
          EXECUTE 'UPDATE model_artifacts SET artifact_path = COALESCE(artifact_path, path::text) WHERE artifact_path IS NULL';
        END IF;
      END $$;

      UPDATE model_artifacts
      SET model_version = COALESCE(model_version, 'elyan-brain-' || encode(digest(coalesce(artifact_path, '') || coalesce(created_at::text, ''), 'sha256'), 'hex')),
          base_model = COALESCE(NULLIF(base_model, ''), 'unknown'),
          dataset_size = COALESCE(dataset_size, 0),
          active = COALESCE(active, false),
          artifact_path = COALESCE(artifact_path, ''),
          metadata = COALESCE(metadata, '{}'::jsonb),
          updated_at = COALESCE(updated_at, NOW());

      ALTER TABLE model_artifacts
        ALTER COLUMN model_version SET NOT NULL,
        ALTER COLUMN base_model SET NOT NULL,
        ALTER COLUMN dataset_size SET NOT NULL,
        ALTER COLUMN active SET NOT NULL,
        ALTER COLUMN artifact_path SET NOT NULL,
        ALTER COLUMN metadata SET NOT NULL,
        ALTER COLUMN created_at SET NOT NULL,
        ALTER COLUMN updated_at SET NOT NULL;

      CREATE UNIQUE INDEX IF NOT EXISTS model_artifacts_model_version_idx
        ON model_artifacts (model_version);

      CREATE INDEX IF NOT EXISTS model_artifacts_created_idx
        ON model_artifacts (created_at DESC);

      CREATE INDEX IF NOT EXISTS model_artifacts_active_score_idx
        ON model_artifacts (active, score DESC, created_at DESC);
    `,
  },
  {
    version: 10,
    name: 'release_cache_ttl',
    sql: `
      ALTER TABLE release_cache
        ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours');

      CREATE INDEX IF NOT EXISTS release_cache_expires_idx
        ON release_cache (expires_at);
    `,
  },
  {
    version: 11,
    name: 'retrieval_documents_pgvector',
    sql: `
      CREATE EXTENSION IF NOT EXISTS vector;

      CREATE TABLE IF NOT EXISTS retrieval_documents (
        document_id TEXT PRIMARY KEY,
        account_id TEXT REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        source_kind TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT,
        title TEXT,
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL UNIQUE,
        embedding vector(384) NOT NULL,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );

      ALTER TABLE retrieval_documents
        ADD COLUMN IF NOT EXISTS document_id TEXT,
        ADD COLUMN IF NOT EXISTS account_id TEXT REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        ADD COLUMN IF NOT EXISTS source_kind TEXT,
        ADD COLUMN IF NOT EXISTS source_name TEXT,
        ADD COLUMN IF NOT EXISTS source_url TEXT,
        ADD COLUMN IF NOT EXISTS title TEXT,
        ADD COLUMN IF NOT EXISTS content_hash TEXT,
        ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1
          FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name = 'retrieval_documents'
            AND column_name = 'id'
        ) THEN
          EXECUTE 'UPDATE retrieval_documents SET document_id = COALESCE(document_id, id::text) WHERE document_id IS NULL';
        END IF;
      END $$;

      UPDATE retrieval_documents
      SET document_id = COALESCE(document_id, 'doc_' || encode(digest(coalesce(content, '') || coalesce(metadata::text, '') || coalesce(created_at::text, ''), 'sha256'), 'hex'))
      WHERE document_id IS NULL;

      UPDATE retrieval_documents
      SET source_kind = COALESCE(NULLIF(source_kind, ''), 'bootstrap'),
          source_name = COALESCE(NULLIF(source_name, ''), 'legacy'),
          content_hash = COALESCE(NULLIF(content_hash, ''), encode(digest(document_id || ':' || coalesce(content, ''), 'sha256'), 'hex')),
          updated_at = COALESCE(updated_at, NOW());

      ALTER TABLE retrieval_documents
        ALTER COLUMN document_id SET NOT NULL,
        ALTER COLUMN source_kind SET NOT NULL,
        ALTER COLUMN source_name SET NOT NULL,
        ALTER COLUMN content_hash SET NOT NULL,
        ALTER COLUMN metadata SET NOT NULL,
        ALTER COLUMN updated_at SET NOT NULL;

      CREATE UNIQUE INDEX IF NOT EXISTS retrieval_documents_document_id_idx
        ON retrieval_documents (document_id);

      CREATE UNIQUE INDEX IF NOT EXISTS retrieval_documents_content_hash_idx
        ON retrieval_documents (content_hash);

      CREATE INDEX IF NOT EXISTS retrieval_documents_account_kind_created_idx
        ON retrieval_documents (account_id, source_kind, created_at DESC);

      CREATE INDEX IF NOT EXISTS retrieval_documents_created_idx
        ON retrieval_documents (created_at DESC);

      CREATE INDEX IF NOT EXISTS retrieval_documents_embedding_idx
        ON retrieval_documents
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);

      CREATE INDEX IF NOT EXISTS retrieval_documents_search_idx
        ON retrieval_documents
        USING gin (
          to_tsvector('english', coalesce(title, '') || ' ' || coalesce(source_name, '') || ' ' || content)
        );
    `,
  },
  {
    version: 12,
    name: 'learning_events_quality_fields',
    sql: `
      ALTER TABLE learning_events
        ADD COLUMN IF NOT EXISTS better_output TEXT NOT NULL DEFAULT '',
        ADD COLUMN IF NOT EXISTS accepted BOOLEAN NOT NULL DEFAULT false;

      ALTER TABLE learning_events
        ADD COLUMN IF NOT EXISTS reasoning_trace JSONB NOT NULL DEFAULT '[]'::jsonb;

      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1
          FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name = 'learning_events'
            AND column_name = 'reasoning_trace'
            AND data_type <> 'jsonb'
        ) THEN
          EXECUTE 'ALTER TABLE learning_events ALTER COLUMN reasoning_trace TYPE jsonb USING CASE WHEN reasoning_trace IS NULL OR btrim(reasoning_trace::text) = '''' THEN ''[]''::jsonb ELSE jsonb_build_array(reasoning_trace::text) END';
        END IF;
      END $$;

      UPDATE learning_events
      SET better_output = COALESCE(better_output, ''),
          reasoning_trace = COALESCE(reasoning_trace, '[]'::jsonb),
          accepted = COALESCE(accepted, false);

      ALTER TABLE learning_events
        ALTER COLUMN better_output SET NOT NULL,
        ALTER COLUMN reasoning_trace SET NOT NULL,
        ALTER COLUMN accepted SET NOT NULL;

      CREATE INDEX IF NOT EXISTS learning_events_quality_idx
        ON learning_events (accepted, score DESC, created_at DESC);
    `,
  },
  {
    version: 13,
    name: 'model_artifacts_quality_promotion',
    sql: `
      ALTER TABLE model_artifacts
        ADD COLUMN IF NOT EXISTS score NUMERIC(10, 6),
        ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT false;

      UPDATE model_artifacts
      SET score = CASE
        WHEN score IS NOT NULL THEN score
        WHEN loss IS NOT NULL THEN ROUND((1 / (1 + loss))::numeric, 6)
        ELSE score
      END;

      WITH best_model AS (
        SELECT model_version
        FROM model_artifacts
        ORDER BY COALESCE(score, 0) DESC, created_at DESC
        LIMIT 1
      )
      UPDATE model_artifacts
      SET active = CASE WHEN model_version = (SELECT model_version FROM best_model) THEN true ELSE false END,
          updated_at = NOW()
      WHERE EXISTS (SELECT 1 FROM best_model);
    `,
  },
  {
    version: 14,
    name: 'retrieval_documents_legacy_repair',
    sql: `
      CREATE EXTENSION IF NOT EXISTS pgcrypto;
      CREATE EXTENSION IF NOT EXISTS vector;

      ALTER TABLE retrieval_documents
        ADD COLUMN IF NOT EXISTS document_id TEXT,
        ADD COLUMN IF NOT EXISTS account_id TEXT REFERENCES elyan_accounts(account_id) ON DELETE CASCADE,
        ADD COLUMN IF NOT EXISTS source_kind TEXT,
        ADD COLUMN IF NOT EXISTS source_name TEXT,
        ADD COLUMN IF NOT EXISTS source_url TEXT,
        ADD COLUMN IF NOT EXISTS title TEXT,
        ADD COLUMN IF NOT EXISTS content_hash TEXT,
        ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

      DO $$
      BEGIN
        IF EXISTS (
          SELECT 1
          FROM information_schema.columns
          WHERE table_schema = 'public'
            AND table_name = 'retrieval_documents'
            AND column_name = 'id'
        ) THEN
          EXECUTE 'UPDATE retrieval_documents SET document_id = COALESCE(document_id, id::text) WHERE document_id IS NULL';
        END IF;
      END $$;

      UPDATE retrieval_documents
      SET document_id = COALESCE(document_id, 'doc_' || encode(digest(coalesce(content, '') || coalesce(metadata::text, '') || coalesce(created_at::text, ''), 'sha256'), 'hex'))
      WHERE document_id IS NULL;

      UPDATE retrieval_documents
      SET source_kind = COALESCE(NULLIF(source_kind, ''), 'bootstrap'),
          source_name = COALESCE(NULLIF(source_name, ''), 'legacy'),
          content_hash = COALESCE(NULLIF(content_hash, ''), encode(digest(document_id || ':' || coalesce(content, ''), 'sha256'), 'hex')),
          updated_at = COALESCE(updated_at, NOW());

      ALTER TABLE retrieval_documents
        ALTER COLUMN document_id SET NOT NULL,
        ALTER COLUMN source_kind SET NOT NULL,
        ALTER COLUMN source_name SET NOT NULL,
        ALTER COLUMN content_hash SET NOT NULL,
        ALTER COLUMN metadata SET NOT NULL,
        ALTER COLUMN updated_at SET NOT NULL;

      CREATE UNIQUE INDEX IF NOT EXISTS retrieval_documents_document_id_idx
        ON retrieval_documents (document_id);

      CREATE UNIQUE INDEX IF NOT EXISTS retrieval_documents_content_hash_idx
        ON retrieval_documents (content_hash);

      CREATE INDEX IF NOT EXISTS retrieval_documents_account_kind_created_idx
        ON retrieval_documents (account_id, source_kind, created_at DESC);

      CREATE INDEX IF NOT EXISTS retrieval_documents_created_idx
        ON retrieval_documents (created_at DESC);

      CREATE INDEX IF NOT EXISTS retrieval_documents_search_idx
        ON retrieval_documents
        USING gin (
          to_tsvector('english', coalesce(title, '') || ' ' || coalesce(source_name, '') || ' ' || content)
        );
    `,
  },
  {
    version: 15,
    name: 'learning_system_signals',
    sql: `
      ALTER TABLE learning_events
        ADD COLUMN IF NOT EXISTS task_type TEXT,
        ADD COLUMN IF NOT EXISTS feedback JSONB NOT NULL DEFAULT '{}'::jsonb,
        ADD COLUMN IF NOT EXISTS is_safe_for_learning BOOLEAN NOT NULL DEFAULT false;

      UPDATE learning_events
      SET task_type = COALESCE(
            NULLIF(task_type, ''),
            NULLIF(metadata->>'task_type', ''),
            NULLIF(metadata->>'taskIntent', ''),
            'direct_answer'
          ),
          feedback = COALESCE(
            feedback,
            CASE
              WHEN metadata ? 'feedback' THEN metadata->'feedback'
              ELSE '{}'::jsonb
            END
          ),
          is_safe_for_learning = COALESCE(is_safe_for_learning, false),
          updated_at = COALESCE(updated_at, NOW());

      ALTER TABLE learning_events
        ALTER COLUMN task_type SET NOT NULL,
        ALTER COLUMN feedback SET NOT NULL,
        ALTER COLUMN is_safe_for_learning SET NOT NULL;

      CREATE INDEX IF NOT EXISTS learning_events_safe_learning_idx
        ON learning_events (is_safe_for_learning, task_type, created_at DESC);

      ALTER TABLE model_artifacts
        ADD COLUMN IF NOT EXISTS artifact_type TEXT,
        ADD COLUMN IF NOT EXISTS source_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
        ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(4, 2),
        ADD COLUMN IF NOT EXISTS is_safe_for_learning BOOLEAN NOT NULL DEFAULT false;

      UPDATE model_artifacts
      SET artifact_type = COALESCE(NULLIF(artifact_type, ''), 'brain_model'),
          source_event_ids = COALESCE(source_event_ids, '[]'::jsonb),
          confidence_score = COALESCE(confidence_score, COALESCE(score, 0)),
          is_safe_for_learning = COALESCE(is_safe_for_learning, false),
          updated_at = COALESCE(updated_at, NOW());

      ALTER TABLE model_artifacts
        ALTER COLUMN artifact_type SET NOT NULL,
        ALTER COLUMN source_event_ids SET NOT NULL,
        ALTER COLUMN confidence_score SET NOT NULL,
        ALTER COLUMN is_safe_for_learning SET NOT NULL;

      CREATE INDEX IF NOT EXISTS model_artifacts_safe_lookup_idx
        ON model_artifacts (is_safe_for_learning, artifact_type, created_at DESC);
    `,
  },
  {
    version: 16,
    name: 'space_context',
    sql: `
      ALTER TABLE learning_events
        ADD COLUMN IF NOT EXISTS space_id TEXT;

      UPDATE learning_events
      SET space_id = COALESCE(
            NULLIF(space_id, ''),
            NULLIF(metadata->>'space_id', ''),
            NULLIF(metadata->>'spaceId', ''),
            account_id
          );

      ALTER TABLE learning_events
        ALTER COLUMN space_id SET NOT NULL;

      CREATE INDEX IF NOT EXISTS learning_events_space_idx
        ON learning_events (space_id, created_at DESC);

      ALTER TABLE model_artifacts
        ADD COLUMN IF NOT EXISTS space_id TEXT;

      UPDATE model_artifacts
      SET space_id = COALESCE(
            NULLIF(space_id, ''),
            NULLIF(metadata->>'space_id', ''),
            NULLIF(metadata->>'spaceId', ''),
            'global'
          );

      ALTER TABLE model_artifacts
        ALTER COLUMN space_id SET NOT NULL;

      CREATE INDEX IF NOT EXISTS model_artifacts_space_idx
        ON model_artifacts (space_id, artifact_type, created_at DESC);

      ALTER TABLE retrieval_documents
        ADD COLUMN IF NOT EXISTS space_id TEXT;

      UPDATE retrieval_documents
      SET space_id = COALESCE(
            NULLIF(space_id, ''),
            NULLIF(metadata->>'space_id', ''),
            NULLIF(metadata->>'spaceId', ''),
            account_id,
            'global'
          );

      ALTER TABLE retrieval_documents
        ALTER COLUMN space_id SET NOT NULL;

      CREATE INDEX IF NOT EXISTS retrieval_documents_space_kind_created_idx
        ON retrieval_documents (space_id, source_kind, created_at DESC);
    `,
  },
];

export const canonicalSharedTruthRelations = [
  'users',
  'accounts',
  'sessions',
  'verification_token',
  'subscriptions',
  'entitlements',
  'token_ledger',
  'usage_counters',
  'usage_events',
  'billing_profiles',
  'notifications',
  'device_link_requests',
  'devices',
  'release_cache',
  'learning_events',
  'model_artifacts',
  'retrieval_documents',
  'schema_migrations',
] as const;

function toVersionSet(rows: Array<{ version: number }>) {
  return new Set(rows.map((row) => row.version));
}

export type ControlPlaneMigrationStatus = {
  initialized: boolean;
  expectedCount: number;
  appliedCount: number;
  appliedVersions: number[];
  missingVersions: Array<Pick<ControlPlaneMigration, 'version' | 'name'>>;
  applied: boolean;
};

async function queryControlPlane<T extends QueryResultRow>(pool: Pool, sql: string, params: unknown[] = []) {
  const poolWithQuery = pool as Pool & { query?: typeof pool.query };

  if (typeof poolWithQuery.query === 'function') {
    return poolWithQuery.query<T>(sql, params);
  }

  const client = await pool.connect();
  try {
    return await client.query<T>(sql, params);
  } finally {
    client.release();
  }
}

export async function readControlPlaneMigrationStatus(pool: Pool): Promise<ControlPlaneMigrationStatus> {
  const exists = await queryControlPlane<{ exists: string | null }>(
    pool,
    `SELECT to_regclass('public.schema_migrations') AS exists`
  );

  if (!exists.rows[0]?.exists) {
    return {
      initialized: false,
      expectedCount: controlPlaneMigrations.length,
      appliedCount: 0,
      appliedVersions: [],
      missingVersions: controlPlaneMigrations.map(({ version, name }) => ({ version, name })),
      applied: false,
    };
  }

  const appliedVersions = (await queryControlPlane<{ version: number }>(
    pool,
    'SELECT version FROM schema_migrations ORDER BY version ASC'
  )).rows.map((row) => row.version);
  const applied = toVersionSet(appliedVersions.map((version) => ({ version })));

  return {
    initialized: true,
    expectedCount: controlPlaneMigrations.length,
    appliedCount: appliedVersions.length,
    appliedVersions,
    missingVersions: controlPlaneMigrations
      .filter((migration) => !applied.has(migration.version))
      .map(({ version, name }) => ({ version, name })),
    applied: controlPlaneMigrations.every((migration) => applied.has(migration.version)),
  };
}

export async function applyControlPlaneMigrations(pool: Pool) {
  const client = await pool.connect();

  try {
    await client.query('BEGIN');
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `);

    const applied = toVersionSet(
      (await client.query<{ version: number }>('SELECT version FROM schema_migrations ORDER BY version ASC')).rows
    );

    for (const migration of controlPlaneMigrations) {
      if (applied.has(migration.version)) {
        continue;
      }

      await client.query(migration.sql);
      await client.query('INSERT INTO schema_migrations (version, name) VALUES ($1, $2)', [
        migration.version,
        migration.name,
      ]);
    }

    await client.query('COMMIT');
  } catch (error) {
    await client.query('ROLLBACK');
    throw error;
  } finally {
    client.release();
  }
}

export async function assertControlPlaneMigrationsApplied(pool: Pool) {
  const status = await readControlPlaneMigrationStatus(pool);

  if (!status.initialized) {
    throw new ControlPlaneConfigurationError(
      'Control-plane PostgreSQL schema is not initialized. Run `npm run db:migrate` before starting the hosted control plane.'
    );
  }

  if (!status.applied) {
    throw new ControlPlaneConfigurationError(
      `Control-plane PostgreSQL migrations are incomplete. Missing versions: ${status.missingVersions
        .map((migration) => `${migration.version}:${migration.name}`)
        .join(', ')}`
    );
  }
}

export function getControlPlaneMigrationVersions() {
  return controlPlaneMigrations.map((migration) => migration.version);
}

export async function readCanonicalSharedTruthSnapshot(pool: Pool) {
  const result = await queryControlPlane<{ table_name: string }>(
    pool,
    `
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = 'public'
        AND table_name = ANY($1::text[])
      ORDER BY table_name
    `,
    [canonicalSharedTruthRelations]
  );
  const present = new Set(result.rows.map((row) => row.table_name));

  return {
    expected: [...canonicalSharedTruthRelations],
    present: canonicalSharedTruthRelations.filter((name) => present.has(name)),
    missing: canonicalSharedTruthRelations.filter((name) => !present.has(name)),
  };
}
