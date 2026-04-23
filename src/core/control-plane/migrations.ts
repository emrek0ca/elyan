import type { Pool } from 'pg';
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
];

function toVersionSet(rows: Array<{ version: number }>) {
  return new Set(rows.map((row) => row.version));
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
  const client = await pool.connect();

  try {
    const exists = await client.query<{ exists: string | null }>(
      `SELECT to_regclass('public.schema_migrations') AS exists`
    );

    if (!exists.rows[0]?.exists) {
      throw new ControlPlaneConfigurationError(
        'Control-plane PostgreSQL schema is not initialized. Run `npm run db:migrate` before starting the hosted control plane.'
      );
    }

    const applied = toVersionSet(
      (await client.query<{ version: number }>('SELECT version FROM schema_migrations ORDER BY version ASC')).rows
    );
    const missing = controlPlaneMigrations.filter((migration) => !applied.has(migration.version));

    if (missing.length > 0) {
      throw new ControlPlaneConfigurationError(
        `Control-plane PostgreSQL migrations are incomplete. Missing versions: ${missing
          .map((migration) => `${migration.version}:${migration.name}`)
          .join(', ')}`
      );
    }
  } finally {
    client.release();
  }
}

export function getControlPlaneMigrationVersions() {
  return controlPlaneMigrations.map((migration) => migration.version);
}
