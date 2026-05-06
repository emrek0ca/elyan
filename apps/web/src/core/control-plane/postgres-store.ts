import { readFile } from 'fs/promises';
import { type PoolClient } from 'pg';
import { createDefaultControlPlaneState, migrateControlPlaneState } from './defaults';
import { getControlPlanePlan } from './catalog';
import { assertControlPlaneMigrationsApplied } from './migrations';
import { getControlPlanePool } from './database';
import { createUsageSnapshot } from './usage';
import type {
  ControlPlaneAccount,
  ControlPlaneBillingPlanBinding,
  ControlPlaneEvaluationSignal,
  ControlPlaneDevice,
  ControlPlaneDeviceLink,
  ControlPlaneLedgerEntry,
  ControlPlaneNotification,
  ControlPlaneIntegration,
  ControlPlaneLearningEvent,
  ControlPlaneState,
  ControlPlaneSubscription,
  ControlPlaneUser,
} from './types';
import {
  controlPlaneEvaluationSignalSchema,
  controlPlaneInteractionStateSchema,
  controlPlaneUsageSnapshotSchema,
} from './types';
import { ControlPlaneStoreError } from './errors';

const LEGACY_STATE_TABLE = 'elyan_control_plane_state';
const LEGACY_STATE_ROW_ID = 1;

const ACCOUNTS_TABLE = 'elyan_accounts';
const SUBSCRIPTIONS_TABLE = 'elyan_subscriptions';
const USERS_TABLE = 'elyan_users';
const LEDGER_TABLE = 'elyan_ledger_entries';
const BILLING_BINDINGS_TABLE = 'elyan_billing_plan_bindings';
const STATUS_EVENTS_TABLE = 'elyan_status_events';
const EVALUATION_SIGNALS_TABLE = 'elyan_evaluation_signals';
const NOTIFICATIONS_TABLE = 'elyan_notifications';
const DEVICE_LINKS_TABLE = 'elyan_device_links';
const DEVICES_TABLE = 'elyan_devices';
const INTEGRATIONS_TABLE = 'elyan_integrations';
const LEARNING_EVENTS_TABLE = 'learning_events';
const CONTROL_PLANE_ADVISORY_LOCK_KEY = 'elyan_control_plane_state';
const CONTROL_PLANE_STATEMENT_TIMEOUT = '30s';
const CONTROL_PLANE_LOCK_TIMEOUT = '5s';

function isHostedBillingReady(subscription: ControlPlaneSubscription) {
  return (
    subscription.provider === 'iyzico' &&
    subscription.syncState === 'synced' &&
    (subscription.status === 'active' || subscription.status === 'trialing')
  );
}

function resolveStoredEntitlements(subscription: ControlPlaneSubscription) {
  const plan = getControlPlanePlan(subscription.planId);
  const hostedReady = plan.entitlements.hostedAccess && isHostedBillingReady(subscription);

  return {
    hostedAccess: hostedReady,
    hostedUsageAccounting: hostedReady && plan.entitlements.hostedUsageAccounting,
    managedCredits: hostedReady && plan.entitlements.managedCredits,
    cloudRouting: hostedReady && plan.entitlements.cloudRouting,
    advancedRouting: hostedReady && plan.entitlements.advancedRouting,
    teamGovernance: hostedReady && plan.entitlements.teamGovernance,
    hostedImprovementSignals: hostedReady && plan.entitlements.hostedImprovementSignals,
  };
}

export interface PostgresControlPlaneStoreConfig {
  databaseUrl: string;
  seedStatePath?: string;
}

type PersistOptions = {
  recordStatusEvents?: boolean;
};

function stringify(value: unknown) {
  return JSON.stringify(value);
}

function parseUsageTotals(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return {};
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => [key, typeof entry === 'string' ? entry : String(entry ?? '0.00')])
  );
}

function parseStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0);
}

function formatNullableText(value: unknown) {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

function normalizeTimestamp(value: unknown) {
  if (!value) {
    return undefined;
  }

  return new Date(String(value)).toISOString();
}

async function applyTransactionGuards(client: PoolClient) {
  await client.query(`SET LOCAL statement_timeout = '${CONTROL_PLANE_STATEMENT_TIMEOUT}'`);
  await client.query(`SET LOCAL lock_timeout = '${CONTROL_PLANE_LOCK_TIMEOUT}'`);
}

async function acquireControlPlaneLock(client: PoolClient) {
  await client.query(`SELECT pg_advisory_xact_lock(hashtext($1))`, [CONTROL_PLANE_ADVISORY_LOCK_KEY]);
}

export async function runClientQueriesSequentially<T>(
  client: Pick<PoolClient, 'query'>,
  queries: Array<() => Promise<T>>
) {
  const results: T[] = [];

  for (const query of queries) {
    results.push(await query());
  }

  return results;
}

export class PostgresControlPlaneStateStore {
  readonly kind = 'postgres' as const;
  private bootstrapPromise: Promise<void> | null = null;

  constructor(private readonly config: PostgresControlPlaneStoreConfig) {
    getControlPlanePool(config.databaseUrl);
  }

  async read(): Promise<ControlPlaneState> {
    await this.ensureBootstrap();

    try {
      const client = await getControlPlanePool(this.config.databaseUrl).connect();
      try {
        return await this.readState(client);
      } finally {
        client.release();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'unknown postgres control plane read failure';
      throw new ControlPlaneStoreError(`Failed to read control-plane state from PostgreSQL: ${message}`);
    }
  }

  async write(state: ControlPlaneState): Promise<void> {
    await this.ensureBootstrap();

    const client = await getControlPlanePool(this.config.databaseUrl).connect();
    try {
      await client.query('BEGIN');
      await applyTransactionGuards(client);
      await acquireControlPlaneLock(client);
      await this.persistState(client, state, { recordStatusEvents: true });
      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      const message = error instanceof Error ? error.message : 'unknown postgres control plane write failure';
      throw new ControlPlaneStoreError(`Failed to write control-plane state to PostgreSQL: ${message}`);
    } finally {
      client.release();
    }
  }

  async close() {
    return;
  }

  private async ensureBootstrap() {
    if (!this.bootstrapPromise) {
      this.bootstrapPromise = this.bootstrap();
    }

    await this.bootstrapPromise;
  }

  private async bootstrap() {
    const pool = getControlPlanePool(this.config.databaseUrl);
    await assertControlPlaneMigrationsApplied(pool);
    const client = await pool.connect();

    try {
      await client.query('BEGIN');
      await applyTransactionGuards(client);
      await acquireControlPlaneLock(client);

      const empty = await this.isNormalizedStoreEmpty(client);
      if (empty) {
        const migrated = await this.migrateLegacyBlobState(client);
        if (!migrated) {
          const seeded = await this.seedState();
          await this.persistState(client, seeded, { recordStatusEvents: false });
        }
      }

      await client.query('COMMIT');
    } catch (error) {
      await client.query('ROLLBACK');
      throw error;
    } finally {
      client.release();
    }
  }

  private async isNormalizedStoreEmpty(client: PoolClient) {
    const result = await client.query<{ count: string }>(`SELECT COUNT(*)::text AS count FROM ${ACCOUNTS_TABLE}`);
    return Number(result.rows[0]?.count ?? '0') === 0;
  }

  private async migrateLegacyBlobState(client: PoolClient) {
    const legacyTableResult = await client.query<{ exists: string | null }>(
      `SELECT to_regclass($1) AS exists`,
      [`public.${LEGACY_STATE_TABLE}`]
    );

    if (!legacyTableResult.rows[0]?.exists) {
      return false;
    }

    const result = await client.query<{ state: ControlPlaneState }>(
      `SELECT state FROM ${LEGACY_STATE_TABLE} WHERE id = $1 LIMIT 1`,
      [LEGACY_STATE_ROW_ID]
    );

    const row = result.rows[0];
    if (!row?.state) {
      return false;
    }

    const migrated = migrateControlPlaneState(row.state);
    await this.persistState(client, migrated, { recordStatusEvents: false });
    return true;
  }

  private async seedState(): Promise<ControlPlaneState> {
    if (!this.config.seedStatePath) {
      return createDefaultControlPlaneState();
    }

    try {
      const raw = await readFile(this.config.seedStatePath, 'utf8');
      return migrateControlPlaneState(JSON.parse(raw));
    } catch {
      return createDefaultControlPlaneState();
    }
  }

  private async readState(client: PoolClient): Promise<ControlPlaneState> {
    const [
      accountsResult,
      subscriptionsResult,
      usersResult,
      ledgerResult,
      evaluationSignalsResult,
      learningEventsResult,
      bindingsResult,
      notificationsResult,
      devicesResult,
      deviceLinksResult,
      integrationsResult,
    ] = await runClientQueriesSequentially(client, [
      () => client.query(`
        SELECT
          account_id,
          owner_user_id,
          display_name,
          owner_type,
          billing_customer_ref,
          status,
          balance_credits::text AS balance_credits,
          usage_totals,
          usage_snapshot,
          interaction_state,
          created_at,
          updated_at
        FROM ${ACCOUNTS_TABLE}
      `),
      () => client.query(`
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
          credits_granted_this_period::text AS credits_granted_this_period,
          processed_webhook_event_refs
        FROM ${SUBSCRIPTIONS_TABLE}
      `),
      () => client.query(`
        SELECT
          user_id,
          account_id,
          email,
          display_name,
          owner_type,
          role,
          password_salt,
          password_hash,
          status,
          created_at,
          updated_at,
          last_login_at
        FROM ${USERS_TABLE}
      `),
      () => client.query(`
        SELECT
          entry_id,
          account_id,
          kind,
          status,
          domain,
          credits_delta::text AS credits_delta,
          balance_after::text AS balance_after,
          source,
          request_id,
          note,
          created_at
        FROM ${LEDGER_TABLE}
        ORDER BY created_at ASC, entry_id ASC
      `),
      () => client.query(`
        SELECT
          signal_id,
          account_id,
          request_id,
          payload,
          created_at
        FROM ${EVALUATION_SIGNALS_TABLE}
        ORDER BY created_at ASC, signal_id ASC
      `),
      () => client.query(`
        SELECT
          event_id,
          account_id,
          space_id,
          request_id,
          source,
          input,
          intent,
          task_type,
          plan,
          reasoning_steps,
          reasoning_trace,
          output,
          better_output,
          success,
          failure_reason,
          feedback,
          latency_ms,
          score,
          accepted,
          model_id,
          model_provider,
          is_safe_for_learning,
          metadata,
          created_at,
          updated_at
        FROM ${LEARNING_EVENTS_TABLE}
        ORDER BY created_at ASC, event_id ASC
      `),
      () => client.query(`
        SELECT
          provider,
          plan_id,
          product_name,
          product_reference_code,
          pricing_plan_name,
          pricing_plan_reference_code,
          currency_code,
          payment_interval,
          payment_interval_count,
          plan_payment_type,
          sync_state,
          last_synced_at,
          last_sync_error
        FROM ${BILLING_BINDINGS_TABLE}
      `),
      () => client.query(`
        SELECT
          notification_id,
          account_id,
          title,
          body,
          kind,
          level,
          seen_at,
          created_at
        FROM ${NOTIFICATIONS_TABLE}
        ORDER BY created_at ASC, notification_id ASC
      `),
      () => client.query(`
        SELECT
          device_id,
          account_id,
          user_id,
          device_label,
          status,
          device_token,
          metadata,
          last_seen_release_tag,
          last_seen_at,
          linked_at,
          revoked_at,
          created_at,
          updated_at
        FROM ${DEVICES_TABLE}
      `),
      () => client.query(`
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
        FROM ${DEVICE_LINKS_TABLE}
      `),
      () => client.query(`
        SELECT
          integration_id,
          account_id,
          provider,
          display_name,
          status,
          scopes,
          surfaces,
          external_account_id,
          external_account_label,
          access_token_ciphertext,
          refresh_token_ciphertext,
          id_token_ciphertext,
          expires_at,
          last_synced_at,
          last_error,
          metadata,
          created_at,
          updated_at
        FROM ${INTEGRATIONS_TABLE}
      `),
    ]);

    const subscriptions = new Map<string, ControlPlaneSubscription>();
    for (const row of subscriptionsResult.rows) {
      subscriptions.set(
        String(row.account_id),
        {
          planId: String(row.plan_id) as ControlPlaneSubscription['planId'],
          status: String(row.status) as ControlPlaneSubscription['status'],
          provider: String(row.provider) as ControlPlaneSubscription['provider'],
          providerCustomerRef: formatNullableText(row.provider_customer_ref),
          providerProductRef: formatNullableText(row.provider_product_ref),
          providerPricingPlanRef: formatNullableText(row.provider_pricing_plan_ref),
          providerSubscriptionRef: formatNullableText(row.provider_subscription_ref),
          providerStatus: formatNullableText(row.provider_status),
          syncState: String(row.sync_state) as ControlPlaneSubscription['syncState'],
          retryCount: Number(row.retry_count ?? 0),
          lastSyncedAt: normalizeTimestamp(row.last_synced_at),
          nextRetryAt: normalizeTimestamp(row.next_retry_at),
          lastSyncError: formatNullableText(row.last_sync_error),
          currentPeriodStartedAt: new Date(String(row.current_period_started_at)).toISOString(),
          currentPeriodEndsAt: new Date(String(row.current_period_ends_at)).toISOString(),
          creditsGrantedThisPeriod: String(row.credits_granted_this_period ?? '0.00'),
          processedWebhookEventRefs: parseStringArray(row.processed_webhook_event_refs),
        }
      );
    }

    const accounts: Record<string, ControlPlaneAccount> = {};
    for (const row of accountsResult.rows) {
      const accountId = String(row.account_id);
      const subscription = subscriptions.get(accountId);
      if (!subscription) {
        continue;
      }
      const plan = getControlPlanePlan(subscription.planId);
      const usageSnapshotResult =
        row.usage_snapshot && typeof row.usage_snapshot === 'object' && !Array.isArray(row.usage_snapshot)
          ? controlPlaneUsageSnapshotSchema.safeParse(row.usage_snapshot)
          : null;
      const usageSnapshot = usageSnapshotResult?.success ? usageSnapshotResult.data : undefined;
      const interactionStateResult =
        row.interaction_state && typeof row.interaction_state === 'object' && !Array.isArray(row.interaction_state)
          ? controlPlaneInteractionStateSchema.safeParse(row.interaction_state)
          : null;
      const interactionState = interactionStateResult?.success
        ? interactionStateResult.data
        : {
            threads: [],
            messages: [],
            memoryItems: [],
            learningDrafts: [],
          };

      accounts[accountId] = {
        accountId,
        ownerUserId: formatNullableText(row.owner_user_id),
        displayName: String(row.display_name),
        ownerType: String(row.owner_type) as ControlPlaneAccount['ownerType'],
        billingCustomerRef: formatNullableText(row.billing_customer_ref),
        status: String(row.status) as ControlPlaneAccount['status'],
        subscription,
        entitlements: resolveStoredEntitlements(subscription),
        balanceCredits: String(row.balance_credits ?? '0.00'),
        usageTotals: parseUsageTotals(row.usage_totals),
        usageSnapshot:
          usageSnapshot ??
          createUsageSnapshot(plan, String(row.balance_credits ?? '0.00'), new Date(), {
            dailyRequests: 0,
            dailyHostedToolActionCalls: 0,
          }),
        integrations: {},
        interactionState,
        createdAt: new Date(String(row.created_at)).toISOString(),
        updatedAt: new Date(String(row.updated_at)).toISOString(),
      };
    }

    const users: Record<string, ControlPlaneUser> = {};
    for (const row of usersResult.rows) {
      users[String(row.user_id)] = {
        userId: String(row.user_id),
        accountId: String(row.account_id),
        email: String(row.email),
        displayName: String(row.display_name),
        ownerType: String(row.owner_type) as ControlPlaneUser['ownerType'],
        role: String(row.role ?? 'owner') as ControlPlaneUser['role'],
        passwordSalt: String(row.password_salt),
        passwordHash: String(row.password_hash),
        status: String(row.status) as ControlPlaneUser['status'],
        createdAt: new Date(String(row.created_at)).toISOString(),
        updatedAt: new Date(String(row.updated_at)).toISOString(),
        lastLoginAt: normalizeTimestamp(row.last_login_at),
      };
    }

    const ledger = ledgerResult.rows.map(
      (row): ControlPlaneLedgerEntry => ({
        entryId: String(row.entry_id),
        accountId: String(row.account_id),
        kind: String(row.kind) as ControlPlaneLedgerEntry['kind'],
        status: String(row.status) as ControlPlaneLedgerEntry['status'],
        domain: formatNullableText(row.domain) as ControlPlaneLedgerEntry['domain'],
        creditsDelta: String(row.credits_delta ?? '0.00'),
        balanceAfter: String(row.balance_after ?? '0.00'),
        source: formatNullableText(row.source) as ControlPlaneLedgerEntry['source'],
        requestId: formatNullableText(row.request_id),
        note: formatNullableText(row.note),
        createdAt: new Date(String(row.created_at)).toISOString(),
      })
    );

    const evaluationSignals = evaluationSignalsResult.rows.map((row): ControlPlaneEvaluationSignal => {
      const payload =
        row.payload && typeof row.payload === 'object' && !Array.isArray(row.payload)
          ? (row.payload as Record<string, unknown>)
          : {};

      return controlPlaneEvaluationSignalSchema.parse({
        signalId: String(row.signal_id),
        accountId: String(row.account_id),
        ...payload,
        requestId: formatNullableText(row.request_id) ?? (typeof payload.requestId === 'string' ? payload.requestId : undefined),
        createdAt: new Date(String(row.created_at)).toISOString(),
      });
    });

    const learningEvents = learningEventsResult.rows.map((row): ControlPlaneLearningEvent => {
      const rawReasoningTrace = Array.isArray(row.reasoning_trace)
        ? row.reasoning_trace
        : Array.isArray(row.reasoning_steps)
          ? row.reasoning_steps
          : [];
      const reasoningSteps = rawReasoningTrace.filter(
        (entry: unknown): entry is string => typeof entry === 'string' && entry.trim().length > 0
      );
      const metadata =
        row.metadata && typeof row.metadata === 'object' && !Array.isArray(row.metadata)
          ? (row.metadata as Record<string, unknown>)
          : {};

      return {
        eventId: String(row.event_id),
        accountId: String(row.account_id),
        spaceId: formatNullableText(row.space_id),
        requestId: String(row.request_id),
        source: String(row.source),
        input: String(row.input),
        intent: String(row.intent) as ControlPlaneLearningEvent['intent'],
        taskType: String(row.task_type ?? row.intent) as ControlPlaneLearningEvent['taskType'],
        plan: String(row.plan),
        reasoningSteps,
        reasoningTrace: reasoningSteps,
        output: String(row.output ?? ''),
        betterOutput: String(row.better_output ?? ''),
        success: Boolean(row.success),
        failureReason: formatNullableText(row.failure_reason),
        feedback:
          row.feedback && typeof row.feedback === 'object' && !Array.isArray(row.feedback)
            ? (row.feedback as Record<string, unknown>)
            : {},
        latencyMs: Number(row.latency_ms ?? 0),
        score: Number(row.score ?? 0),
        accepted: Boolean(row.accepted),
        modelId: formatNullableText(row.model_id),
        modelProvider: formatNullableText(row.model_provider),
        isSafeForLearning: Boolean(row.is_safe_for_learning),
        createdAt: new Date(String(row.created_at)).toISOString(),
        updatedAt: new Date(String(row.updated_at)).toISOString(),
        metadata,
      };
    });

    const plans = Object.fromEntries(
      bindingsResult.rows.map((row) => [
        String(row.plan_id),
        {
          provider: 'iyzico',
          planId: String(row.plan_id) as ControlPlaneBillingPlanBinding['planId'],
          productName: String(row.product_name),
          productReferenceCode: formatNullableText(row.product_reference_code),
          pricingPlanName: String(row.pricing_plan_name),
          pricingPlanReferenceCode: formatNullableText(row.pricing_plan_reference_code),
          currencyCode: String(row.currency_code) as ControlPlaneBillingPlanBinding['currencyCode'],
          paymentInterval: String(row.payment_interval) as ControlPlaneBillingPlanBinding['paymentInterval'],
          paymentIntervalCount: Number(row.payment_interval_count),
          planPaymentType: String(row.plan_payment_type) as ControlPlaneBillingPlanBinding['planPaymentType'],
          syncState: String(row.sync_state) as ControlPlaneBillingPlanBinding['syncState'],
          lastSyncedAt: normalizeTimestamp(row.last_synced_at),
          lastSyncError: formatNullableText(row.last_sync_error),
        } satisfies ControlPlaneBillingPlanBinding,
      ])
    );

    const notifications = notificationsResult.rows.map(
      (row): ControlPlaneNotification => ({
        notificationId: String(row.notification_id),
        accountId: String(row.account_id),
        title: String(row.title),
        body: String(row.body),
        kind: String(row.kind) as ControlPlaneNotification['kind'],
        level: String(row.level) as ControlPlaneNotification['level'],
        seenAt: normalizeTimestamp(row.seen_at),
        createdAt: new Date(String(row.created_at)).toISOString(),
      })
    );

    const devices = Object.fromEntries(
      devicesResult.rows.map((row) => [
        String(row.device_id),
        {
          deviceId: String(row.device_id),
          accountId: String(row.account_id),
          userId: String(row.user_id),
          deviceLabel: String(row.device_label),
          status: String(row.status) as ControlPlaneDevice['status'],
          deviceToken: String(row.device_token),
          metadata:
            row.metadata && typeof row.metadata === 'object' && !Array.isArray(row.metadata)
              ? (row.metadata as Record<string, unknown>)
              : {},
          lastSeenReleaseTag: formatNullableText(row.last_seen_release_tag),
          lastSeenAt: normalizeTimestamp(row.last_seen_at),
          linkedAt: new Date(String(row.linked_at)).toISOString(),
          revokedAt: normalizeTimestamp(row.revoked_at),
          createdAt: new Date(String(row.created_at)).toISOString(),
          updatedAt: new Date(String(row.updated_at)).toISOString(),
        } satisfies ControlPlaneDevice,
      ])
    );

    const deviceLinks = Object.fromEntries(
      deviceLinksResult.rows.map((row) => [
        String(row.link_code),
        {
          linkCode: String(row.link_code),
          accountId: String(row.account_id),
          userId: String(row.user_id),
          deviceLabel: String(row.device_label),
          status: String(row.status) as ControlPlaneDeviceLink['status'],
          expiresAt: new Date(String(row.expires_at)).toISOString(),
          createdAt: new Date(String(row.created_at)).toISOString(),
          completedAt: normalizeTimestamp(row.completed_at),
          consumedAt: normalizeTimestamp(row.consumed_at),
          deviceToken: formatNullableText(row.device_token),
        } satisfies ControlPlaneDeviceLink,
      ])
    );

    const integrations = Object.fromEntries(
      integrationsResult.rows.map((row) => [
        String(row.integration_id),
        {
          integrationId: String(row.integration_id),
          accountId: String(row.account_id),
          provider: String(row.provider) as ControlPlaneIntegration['provider'],
          displayName: String(row.display_name),
          status: String(row.status) as ControlPlaneIntegration['status'],
          scopes: parseStringArray(row.scopes),
          surfaces: parseStringArray(row.surfaces) as ControlPlaneIntegration['surfaces'],
          externalAccountId: formatNullableText(row.external_account_id),
          externalAccountLabel: formatNullableText(row.external_account_label),
          accessTokenCiphertext: formatNullableText(row.access_token_ciphertext),
          refreshTokenCiphertext: formatNullableText(row.refresh_token_ciphertext),
          idTokenCiphertext: formatNullableText(row.id_token_ciphertext),
          expiresAt: normalizeTimestamp(row.expires_at),
          lastSyncedAt: normalizeTimestamp(row.last_synced_at),
          lastError: formatNullableText(row.last_error),
          metadata:
            row.metadata && typeof row.metadata === 'object' && !Array.isArray(row.metadata)
              ? (row.metadata as Record<string, unknown>)
              : {},
          createdAt: new Date(String(row.created_at)).toISOString(),
          updatedAt: new Date(String(row.updated_at)).toISOString(),
        } satisfies ControlPlaneIntegration,
      ])
    );

    for (const account of Object.values(accounts)) {
      account.integrations = Object.fromEntries(
        Object.values(integrations)
          .filter((integration) => integration.accountId === account.accountId)
          .map((integration) => [integration.integrationId, integration])
      );
    }

    return migrateControlPlaneState({
      version: 6,
      accounts,
      users,
      ledger,
      notifications,
      billing: {
        iyzico: {
          plans,
        },
      },
      devices,
      deviceLinks,
      evaluationSignals,
      learningEvents,
    });
  }

  private async persistState(client: PoolClient, state: ControlPlaneState, options: PersistOptions) {
    const previousState = options.recordStatusEvents ? await this.readState(client) : createDefaultControlPlaneState();

    for (const account of Object.values(state.accounts)) {
      await client.query(
        `
          INSERT INTO ${ACCOUNTS_TABLE} (
            account_id,
            owner_user_id,
            display_name,
            owner_type,
            billing_customer_ref,
            status,
            balance_credits,
            usage_totals,
            usage_snapshot,
            interaction_state,
            created_at,
            updated_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7::numeric, $8::jsonb, $9::jsonb, $10::jsonb, $11::timestamptz, $12::timestamptz)
          ON CONFLICT (account_id) DO UPDATE SET
            owner_user_id = EXCLUDED.owner_user_id,
            display_name = EXCLUDED.display_name,
            owner_type = EXCLUDED.owner_type,
            billing_customer_ref = EXCLUDED.billing_customer_ref,
            status = EXCLUDED.status,
            balance_credits = EXCLUDED.balance_credits,
            usage_totals = EXCLUDED.usage_totals,
            usage_snapshot = EXCLUDED.usage_snapshot,
            interaction_state = EXCLUDED.interaction_state,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at
        `,
        [
          account.accountId,
          account.ownerUserId ?? null,
          account.displayName,
          account.ownerType,
          account.billingCustomerRef ?? null,
          account.status,
          account.balanceCredits,
          stringify(account.usageTotals),
          stringify(account.usageSnapshot),
          stringify(account.interactionState),
          account.createdAt,
          account.updatedAt,
        ]
      );

      await client.query(
        `
          INSERT INTO ${SUBSCRIPTIONS_TABLE} (
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
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::timestamptz, $13::timestamptz, $14, $15::timestamptz, $16::timestamptz, $17::numeric, $18::jsonb)
          ON CONFLICT (account_id) DO UPDATE SET
            plan_id = EXCLUDED.plan_id,
            status = EXCLUDED.status,
            provider = EXCLUDED.provider,
            provider_customer_ref = EXCLUDED.provider_customer_ref,
            provider_product_ref = EXCLUDED.provider_product_ref,
            provider_pricing_plan_ref = EXCLUDED.provider_pricing_plan_ref,
            provider_subscription_ref = EXCLUDED.provider_subscription_ref,
            provider_status = EXCLUDED.provider_status,
            sync_state = EXCLUDED.sync_state,
            retry_count = EXCLUDED.retry_count,
            last_synced_at = EXCLUDED.last_synced_at,
            next_retry_at = EXCLUDED.next_retry_at,
            last_sync_error = EXCLUDED.last_sync_error,
            current_period_started_at = EXCLUDED.current_period_started_at,
            current_period_ends_at = EXCLUDED.current_period_ends_at,
            credits_granted_this_period = EXCLUDED.credits_granted_this_period,
            processed_webhook_event_refs = EXCLUDED.processed_webhook_event_refs
        `,
        [
          account.accountId,
          account.subscription.planId,
          account.subscription.status,
          account.subscription.provider,
          account.subscription.providerCustomerRef ?? null,
          account.subscription.providerProductRef ?? null,
          account.subscription.providerPricingPlanRef ?? null,
          account.subscription.providerSubscriptionRef ?? null,
          account.subscription.providerStatus ?? null,
          account.subscription.syncState,
          account.subscription.retryCount,
          account.subscription.lastSyncedAt ?? null,
          account.subscription.nextRetryAt ?? null,
          account.subscription.lastSyncError ?? null,
          account.subscription.currentPeriodStartedAt,
          account.subscription.currentPeriodEndsAt,
          account.subscription.creditsGrantedThisPeriod,
          stringify(account.subscription.processedWebhookEventRefs ?? []),
        ]
      );
    }

    for (const user of Object.values(state.users)) {
      await client.query(
        `
          INSERT INTO ${USERS_TABLE} (
            user_id,
            account_id,
            email,
            display_name,
            owner_type,
            role,
            password_salt,
            password_hash,
            status,
            created_at,
            updated_at,
            last_login_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::timestamptz, $11::timestamptz, $12::timestamptz)
          ON CONFLICT (user_id) DO UPDATE SET
            account_id = EXCLUDED.account_id,
            email = EXCLUDED.email,
            display_name = EXCLUDED.display_name,
            owner_type = EXCLUDED.owner_type,
            role = EXCLUDED.role,
            password_salt = EXCLUDED.password_salt,
            password_hash = EXCLUDED.password_hash,
            status = EXCLUDED.status,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at,
            last_login_at = EXCLUDED.last_login_at
        `,
        [
          user.userId,
          user.accountId,
          user.email,
          user.displayName,
          user.ownerType,
          user.role,
          user.passwordSalt,
          user.passwordHash,
          user.status,
          user.createdAt,
          user.updatedAt,
          user.lastLoginAt ?? null,
        ]
      );
    }

    await client.query(`DELETE FROM ${LEDGER_TABLE}`);
    for (const entry of state.ledger) {
      await client.query(
        `
          INSERT INTO ${LEDGER_TABLE} (
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
          )
          VALUES ($1, $2, $3, $4, $5, $6::numeric, $7::numeric, $8, $9, $10, $11::timestamptz)
        `,
        [
          entry.entryId,
          entry.accountId,
          entry.kind,
          entry.status,
          entry.domain ?? null,
          entry.creditsDelta,
          entry.balanceAfter,
          entry.source ?? null,
          entry.requestId ?? null,
          entry.note ?? null,
          entry.createdAt,
        ]
      );
    }

    await client.query(`DELETE FROM ${EVALUATION_SIGNALS_TABLE}`);
    for (const signal of state.evaluationSignals) {
      await client.query(
        `
          INSERT INTO ${EVALUATION_SIGNALS_TABLE} (
            signal_id,
            account_id,
            request_id,
            payload,
            created_at
          )
          VALUES ($1, $2, $3, $4::jsonb, $5::timestamptz)
        `,
        [
          signal.signalId,
          signal.accountId,
          signal.requestId ?? null,
          stringify({
            requestId: signal.requestId ?? null,
            mode: signal.mode,
            surface: signal.surface,
            model: signal.model,
            taskIntent: signal.taskIntent,
            reasoningDepth: signal.reasoningDepth,
            routingMode: signal.routingMode,
            intentConfidence: signal.intentConfidence,
            retrieval: signal.retrieval,
            tooling: signal.tooling,
            usage: signal.usage,
            latencyMs: signal.latencyMs,
            queryLength: signal.queryLength,
            answerLength: signal.answerLength,
            quality: signal.quality,
            promotionCandidate: signal.promotionCandidate,
            notes: signal.notes,
          }),
          signal.createdAt,
        ]
      );
    }

    await client.query(`DELETE FROM ${LEARNING_EVENTS_TABLE}`);
    for (const event of state.learningEvents) {
      await client.query(
        `
          INSERT INTO ${LEARNING_EVENTS_TABLE} (
            event_id,
            account_id,
            space_id,
            request_id,
            source,
            input,
            intent,
            task_type,
            plan,
            reasoning_steps,
            reasoning_trace,
            output,
            better_output,
            success,
            failure_reason,
            feedback,
            latency_ms,
            score,
            accepted,
            model_id,
            model_provider,
            is_safe_for_learning,
            metadata,
            created_at,
            updated_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, $12, $13, $14, $15::jsonb, $16, $17::numeric, $18, $19, $20, $21, $22::jsonb, $23::timestamptz, $24::timestamptz)
        `,
        [
          event.eventId,
          event.accountId,
          event.spaceId ?? event.accountId,
          event.requestId,
          event.source,
          event.input,
          event.intent,
          event.taskType,
          event.plan,
          stringify(event.reasoningSteps ?? []),
          stringify(event.reasoningSteps ?? []),
          event.output,
          event.betterOutput ?? '',
          event.success,
          event.failureReason ?? null,
          stringify(event.feedback ?? {}),
          event.latencyMs,
          event.score,
          event.accepted,
          event.modelId ?? null,
          event.modelProvider ?? null,
          event.isSafeForLearning ?? false,
          stringify(event.metadata ?? {}),
          event.createdAt,
          event.updatedAt,
        ]
      );
    }

    await client.query(`DELETE FROM ${BILLING_BINDINGS_TABLE}`);
    for (const binding of Object.values(state.billing.iyzico.plans)) {
      await client.query(
        `
          INSERT INTO ${BILLING_BINDINGS_TABLE} (
            provider,
            plan_id,
            product_name,
            product_reference_code,
            pricing_plan_name,
            pricing_plan_reference_code,
            currency_code,
            payment_interval,
            payment_interval_count,
            plan_payment_type,
            sync_state,
            last_synced_at,
            last_sync_error
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::timestamptz, $13)
        `,
        [
          binding.provider,
          binding.planId,
          binding.productName,
          binding.productReferenceCode ?? null,
          binding.pricingPlanName,
          binding.pricingPlanReferenceCode ?? null,
          binding.currencyCode,
          binding.paymentInterval,
          binding.paymentIntervalCount,
          binding.planPaymentType,
          binding.syncState,
          binding.lastSyncedAt ?? null,
          binding.lastSyncError ?? null,
        ]
      );
    }

    await client.query(`DELETE FROM ${NOTIFICATIONS_TABLE}`);
    for (const notification of state.notifications) {
      await client.query(
        `
          INSERT INTO ${NOTIFICATIONS_TABLE} (
            notification_id,
            account_id,
            title,
            body,
            kind,
            level,
            seen_at,
            created_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7::timestamptz, $8::timestamptz)
        `,
        [
          notification.notificationId,
          notification.accountId,
          notification.title,
          notification.body,
          notification.kind,
          notification.level,
          notification.seenAt ?? null,
          notification.createdAt,
        ]
      );
    }

    await client.query(`DELETE FROM ${DEVICES_TABLE}`);
    for (const device of Object.values(state.devices)) {
      await client.query(
        `
          INSERT INTO ${DEVICES_TABLE} (
            device_id,
            account_id,
            user_id,
            device_label,
            status,
            device_token,
            metadata,
            last_seen_release_tag,
            last_seen_at,
            linked_at,
            revoked_at,
            created_at,
            updated_at
          )
          VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::timestamptz, $10::timestamptz, $11::timestamptz, $12::timestamptz, $13::timestamptz)
          ON CONFLICT (device_id) DO UPDATE SET
            account_id = EXCLUDED.account_id,
            user_id = EXCLUDED.user_id,
            device_label = EXCLUDED.device_label,
            status = EXCLUDED.status,
            device_token = EXCLUDED.device_token,
            metadata = EXCLUDED.metadata,
            last_seen_release_tag = EXCLUDED.last_seen_release_tag,
            last_seen_at = EXCLUDED.last_seen_at,
            linked_at = EXCLUDED.linked_at,
            revoked_at = EXCLUDED.revoked_at,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at
        `,
        [
          device.deviceId,
          device.accountId,
          device.userId,
          device.deviceLabel,
          device.status,
          device.deviceToken,
          stringify(device.metadata),
          device.lastSeenReleaseTag ?? null,
          device.lastSeenAt ?? null,
          device.linkedAt,
          device.revokedAt ?? null,
          device.createdAt,
          device.updatedAt,
        ]
      );
    }

    await client.query(`DELETE FROM ${INTEGRATIONS_TABLE}`);
    for (const integration of Object.values(state.accounts).flatMap((account) => Object.values(account.integrations ?? {}))) {
      await client.query(
        `
          INSERT INTO ${INTEGRATIONS_TABLE} (
            integration_id,
            account_id,
            provider,
            display_name,
            status,
            scopes,
            surfaces,
            external_account_id,
            external_account_label,
            access_token_ciphertext,
            refresh_token_ciphertext,
            id_token_ciphertext,
            expires_at,
            last_synced_at,
            last_error,
            metadata,
            created_at,
            updated_at
          )
          VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12, $13::timestamptz, $14::timestamptz, $15, $16::jsonb, $17::timestamptz, $18::timestamptz)
          ON CONFLICT (integration_id) DO UPDATE SET
            account_id = EXCLUDED.account_id,
            provider = EXCLUDED.provider,
            display_name = EXCLUDED.display_name,
            status = EXCLUDED.status,
            scopes = EXCLUDED.scopes,
            surfaces = EXCLUDED.surfaces,
            external_account_id = EXCLUDED.external_account_id,
            external_account_label = EXCLUDED.external_account_label,
            access_token_ciphertext = EXCLUDED.access_token_ciphertext,
            refresh_token_ciphertext = EXCLUDED.refresh_token_ciphertext,
            id_token_ciphertext = EXCLUDED.id_token_ciphertext,
            expires_at = EXCLUDED.expires_at,
            last_synced_at = EXCLUDED.last_synced_at,
            last_error = EXCLUDED.last_error,
            metadata = EXCLUDED.metadata,
            created_at = EXCLUDED.created_at,
            updated_at = EXCLUDED.updated_at
        `,
        [
          integration.integrationId,
          integration.accountId,
          integration.provider,
          integration.displayName,
          integration.status,
          stringify(integration.scopes ?? []),
          stringify(integration.surfaces ?? []),
          integration.externalAccountId ?? null,
          integration.externalAccountLabel ?? null,
          integration.accessTokenCiphertext ?? null,
          integration.refreshTokenCiphertext ?? null,
          integration.idTokenCiphertext ?? null,
          integration.expiresAt ?? null,
          integration.lastSyncedAt ?? null,
          integration.lastError ?? null,
          stringify(integration.metadata ?? {}),
          integration.createdAt,
          integration.updatedAt,
        ]
      );
    }

    await client.query(`DELETE FROM ${DEVICE_LINKS_TABLE}`);
    for (const link of Object.values(state.deviceLinks)) {
      await client.query(
        `
          INSERT INTO ${DEVICE_LINKS_TABLE} (
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
          )
          VALUES ($1, $2, $3, $4, $5, $6::timestamptz, $7::timestamptz, $8::timestamptz, $9::timestamptz, $10)
          ON CONFLICT (link_code) DO UPDATE SET
            account_id = EXCLUDED.account_id,
            user_id = EXCLUDED.user_id,
            device_label = EXCLUDED.device_label,
            status = EXCLUDED.status,
            expires_at = EXCLUDED.expires_at,
            created_at = EXCLUDED.created_at,
            completed_at = EXCLUDED.completed_at,
            consumed_at = EXCLUDED.consumed_at,
            device_token = EXCLUDED.device_token
        `,
        [
          link.linkCode,
          link.accountId,
          link.userId,
          link.deviceLabel,
          link.status,
          link.expiresAt,
          link.createdAt,
          link.completedAt ?? null,
          link.consumedAt ?? null,
          link.deviceToken ?? null,
        ]
      );
    }

    await this.deleteMissingRows(client, USERS_TABLE, 'user_id', Object.keys(state.users));
    await this.deleteMissingRows(client, SUBSCRIPTIONS_TABLE, 'account_id', Object.keys(state.accounts));
    await this.deleteMissingRows(client, ACCOUNTS_TABLE, 'account_id', Object.keys(state.accounts));
    await this.deleteMissingRows(client, DEVICES_TABLE, 'device_id', Object.keys(state.devices));
    await this.deleteMissingRows(client, INTEGRATIONS_TABLE, 'integration_id', Object.values(state.accounts).flatMap((account) => Object.keys(account.integrations ?? {})));
    await this.deleteMissingRows(client, DEVICE_LINKS_TABLE, 'link_code', Object.keys(state.deviceLinks));

    if (options.recordStatusEvents) {
      await this.recordStatusEvents(client, previousState, state);
    }
  }

  private async deleteMissingRows(client: PoolClient, table: string, column: string, ids: string[]) {
    if (ids.length === 0) {
      await client.query(`DELETE FROM ${table}`);
      return;
    }

    await client.query(`DELETE FROM ${table} WHERE NOT (${column} = ANY($1::text[]))`, [ids]);
  }

  private async recordStatusEvents(client: PoolClient, previousState: ControlPlaneState, nextState: ControlPlaneState) {
    for (const account of Object.values(nextState.accounts)) {
      const previous = previousState.accounts[account.accountId];

      if (!previous) {
        await this.insertStatusEvent(client, account.accountId, 'account.created', null, account, 'account created');
        continue;
      }

      if (previous.status !== account.status) {
        await this.insertStatusEvent(
          client,
          account.accountId,
          'account.status_changed',
          { status: previous.status },
          { status: account.status },
          'account status transition'
        );
      }

      if (previous.subscription.planId !== account.subscription.planId) {
        await this.insertStatusEvent(
          client,
          account.accountId,
          'subscription.plan_changed',
          { planId: previous.subscription.planId },
          { planId: account.subscription.planId },
          'subscription plan transition'
        );
      }

      if (previous.subscription.status !== account.subscription.status) {
        await this.insertStatusEvent(
          client,
          account.accountId,
          'subscription.status_changed',
          { status: previous.subscription.status },
          { status: account.subscription.status },
          'subscription status transition'
        );
      }

      if (previous.subscription.syncState !== account.subscription.syncState) {
        await this.insertStatusEvent(
          client,
          account.accountId,
          'subscription.sync_state_changed',
          { syncState: previous.subscription.syncState },
          { syncState: account.subscription.syncState },
          'subscription sync transition'
        );
      }
    }
  }

  private async insertStatusEvent(
    client: PoolClient,
    accountId: string,
    eventType: string,
    previousState: unknown,
    nextState: unknown,
    note: string
  ) {
    await client.query(
      `
        INSERT INTO ${STATUS_EVENTS_TABLE} (account_id, event_type, previous_state, next_state, note)
        VALUES ($1, $2, $3::jsonb, $4::jsonb, $5)
      `,
      [accountId, eventType, previousState ? stringify(previousState) : null, stringify(nextState), note]
    );
  }
}
