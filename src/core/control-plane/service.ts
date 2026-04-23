import { randomUUID } from 'crypto';
import Decimal from 'decimal.js';
import { controlPlanePlanCatalog, getControlPlanePlan } from './catalog';
import { hashControlPlanePassword, normalizeIdentityEmail, verifyControlPlanePassword } from './identity';
import {
  ControlPlaneAuthenticationError,
  ControlPlaneConfigurationError,
  ControlPlaneConflictError,
  ControlPlaneEntitlementError,
  ControlPlaneInsufficientCreditsError,
  ControlPlaneNotFoundError,
  ControlPlaneProviderError,
  ControlPlaneUsageLimitError,
  ControlPlaneValidationError,
} from './errors';
import { getIyzicoBillingClient, buildIyzicoPlanBinding, type IyzicoSubscriptionWebhook } from './iyzico';
import { buildControlPlaneConnectionSnapshot, buildControlPlaneRuntimeSnapshot } from './runtime';
import { FileControlPlaneStateStore, type ControlPlaneStateStore } from './store';
import { PostgresControlPlaneStateStore } from './postgres-store';
import {
  advanceUsageSnapshot,
  createUsageSnapshot,
  describeUsageLimitDenial,
  evaluateUsageConsumption,
  normalizeUsageSnapshot,
} from './usage';
import type {
  ControlPlaneAccount,
  ControlPlaneAccountUpsertInput,
  ControlPlaneBillingPlanBinding,
  ControlPlaneEvaluationSignal,
  ControlPlaneEvaluationSignalDraft,
  ControlPlaneDevice,
  ControlPlaneDeviceLink,
  ControlPlaneDeviceLinkCompleteInput,
  ControlPlaneDeviceLinkStartInput,
  ControlPlaneDevicePushInput,
  ControlPlaneEntitlements,
  ControlPlaneHostedSession,
  ControlPlaneLedgerEntry,
  ControlPlaneNotification,
  ControlPlaneState,
  ControlPlaneUsageInput,
  ControlPlaneUsageQuote,
  ControlPlaneIdentityRegisterInput,
  ControlPlaneUser,
} from './types';

const CREDIT_SCALE = 2;
const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;
const BILLING_RETRY_WINDOW_MS = 15 * 60 * 1000;

function formatCredits(value: Decimal.Value): string {
  return new Decimal(value).toFixed(CREDIT_SCALE);
}

function addCredits(left: Decimal.Value, right: Decimal.Value): string {
  return formatCredits(new Decimal(left).plus(right));
}

function createId(prefix: string) {
  return `${prefix}_${randomUUID().replace(/-/g, '')}`;
}

function createLedgerEntry(
  input: Omit<ControlPlaneLedgerEntry, 'entryId' | 'createdAt'> & {
    entryId?: string;
    createdAt?: string;
  }
): ControlPlaneLedgerEntry {
  return {
    ...input,
    entryId: input.entryId ?? randomUUID(),
    createdAt: input.createdAt ?? new Date().toISOString(),
  };
}

function createUsageTotals() {
  return {
    inference: '0.00',
    retrieval: '0.00',
    integrations: '0.00',
    evaluation: '0.00',
  };
}

function createAccountUsageSnapshot(
  plan: ReturnType<typeof getControlPlanePlan>,
  balanceCredits: Decimal.Value,
  now = new Date(),
  counters?: {
    dailyRequests?: number;
    dailyHostedToolActionCalls?: number;
  }
) {
  return createUsageSnapshot(plan, balanceCredits, now, counters);
}

function splitDisplayName(displayName: string) {
  const parts = displayName.trim().split(/\s+/).filter(Boolean);
  const [first = 'Elyan', ...rest] = parts;
  return {
    name: first,
    surname: rest.join(' ') || 'User',
  };
}

function createSubscriptionSkeleton(
  planId: ControlPlaneAccount['subscription']['planId'],
  createdAt: string
): ControlPlaneAccount['subscription'] {
  const plan = getControlPlanePlan(planId);
  const hosted = plan.entitlements.hostedAccess;

  return {
    planId: plan.id,
    status: hosted ? 'trialing' : 'active',
    provider: 'manual' as const,
    syncState: hosted ? 'pending' : 'unbound',
    retryCount: 0,
    currentPeriodStartedAt: createdAt,
    currentPeriodEndsAt: new Date(Date.parse(createdAt) + THIRTY_DAYS_MS).toISOString(),
    creditsGrantedThisPeriod: '0.00',
    processedWebhookEventRefs: [],
  };
}

function isHostedBillingReady(subscription: ControlPlaneAccount['subscription']) {
  return (
    subscription.provider === 'iyzico' &&
    subscription.syncState === 'synced' &&
    (subscription.status === 'active' || subscription.status === 'trialing')
  );
}

function resolveEntitlements(
  plan: ReturnType<typeof getControlPlanePlan>,
  subscription: ControlPlaneAccount['subscription']
): ControlPlaneEntitlements {
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

function createEmptyAccount(
  accountId: string,
  input: ControlPlaneAccountUpsertInput,
  createdAt: string
): ControlPlaneAccount {
  const plan = getControlPlanePlan(input.planId);
  const subscription = createSubscriptionSkeleton(plan.id, createdAt);

  return {
    accountId,
    ownerUserId: input.ownerUserId,
    displayName: input.displayName,
    ownerType: input.ownerType,
    billingCustomerRef: input.billingCustomerRef,
    status: subscription.status,
    subscription,
    entitlements: resolveEntitlements(plan, subscription),
    balanceCredits: '0.00',
    usageTotals: createUsageTotals(),
    usageSnapshot: createAccountUsageSnapshot(plan, '0.00', new Date(createdAt), {
      dailyRequests: 0,
      dailyHostedToolActionCalls: 0,
    }),
    createdAt,
    updatedAt: createdAt,
  };
}

function reconcileSubscription(
  account: ControlPlaneAccount,
  nextPlanId: ControlPlaneAccount['subscription']['planId'],
  updatedAt: string,
  nextBillingCustomerRef?: string
): ControlPlaneAccount['subscription'] {
  const nextPlan = getControlPlanePlan(nextPlanId);
  const planChanged = account.subscription.planId !== nextPlan.id;
  const hosted = nextPlan.entitlements.hostedAccess;

  if (!planChanged) {
    return account.subscription;
  }

  const nextSubscription = createSubscriptionSkeleton(nextPlan.id, updatedAt);

  if (hosted) {
    nextSubscription.provider = account.subscription.provider === 'iyzico' ? 'iyzico' : 'manual';
    nextSubscription.syncState = account.subscription.provider === 'iyzico' ? 'pending' : 'pending';
    nextSubscription.providerCustomerRef =
      account.subscription.providerCustomerRef ?? nextBillingCustomerRef ?? account.billingCustomerRef;
  } else {
    nextSubscription.provider = 'manual';
    nextSubscription.syncState = 'unbound';
  }

  if (hosted) {
    nextSubscription.providerProductRef = undefined;
    nextSubscription.providerPricingPlanRef = undefined;
    nextSubscription.providerSubscriptionRef = undefined;
    nextSubscription.providerStatus = undefined;
  }

  return {
    ...nextSubscription,
    retryCount: 0,
    lastSyncedAt: undefined,
    nextRetryAt: undefined,
    lastSyncError: undefined,
  };
}

function getHostedBalanceTopUp(account: ControlPlaneAccount, planId: ControlPlaneAccount['subscription']['planId']) {
  const plan = getControlPlanePlan(planId);
  return new Decimal(plan.monthlyIncludedCredits).minus(account.balanceCredits);
}

function buildIyzicoWebhookEventRef(payload: IyzicoSubscriptionWebhook) {
  return [
    payload.iyziEventType,
    payload.subscriptionReferenceCode,
    payload.orderReferenceCode,
    payload.customerReferenceCode,
    payload.iyziReferenceCode,
  ].join(':');
}

function appendProcessedWebhookEventRef(
  refs: string[],
  eventRef: string,
  limit = 100
) {
  if (refs.includes(eventRef)) {
    return refs;
  }

  const nextRefs = [...refs, eventRef];
  return nextRefs.length > limit ? nextRefs.slice(-limit) : nextRefs;
}

type PreparedUsageCharge = {
  input: ControlPlaneUsageInput;
  rate: Decimal;
  creditsDelta: Decimal;
};

function prepareUsageCharges(account: ControlPlaneAccount, inputs: ControlPlaneUsageInput[]) {
  const plan = getControlPlanePlan(account.subscription.planId);
  const balanceBefore = new Decimal(account.balanceCredits);
  const charges = inputs.map((input) => {
    const rate = new Decimal(plan.rateCard[input.domain]);
    const creditsDelta = rate.mul(input.units);

    return {
      input,
      rate,
      creditsDelta,
    } satisfies PreparedUsageCharge;
  });

  const totalCreditsDelta = charges.reduce((total, charge) => total.plus(charge.creditsDelta), new Decimal(0));
  const balanceAfter = balanceBefore.minus(totalCreditsDelta);

  return {
    plan,
    balanceBefore,
    balanceAfter,
    charges,
    totalCreditsDelta,
    allowed: balanceAfter.greaterThanOrEqualTo(0),
  };
}

function buildAccountView(state: ControlPlaneState, account: ControlPlaneAccount) {
  const accountEvaluationSignals = state.evaluationSignals.filter(
    (signal) => signal.accountId === account.accountId
  );
  const recentEvaluationSignals = accountEvaluationSignals.slice(-10).reverse();
  const plan = getControlPlanePlan(account.subscription.planId);
  const usageSnapshot = normalizeUsageSnapshot(account.usageSnapshot, plan, account.balanceCredits);

  return {
    ...account,
    usageSnapshot,
    plan: getControlPlanePlan(account.subscription.planId),
    processedWebhookEventCount: account.subscription.processedWebhookEventRefs.length,
    recentLedgerEntries: state.ledger
      .filter((entry) => entry.accountId === account.accountId)
      .slice(-10)
      .reverse(),
    recentEvaluationSignals,
    evaluationSignalCount: accountEvaluationSignals.length,
  };
}

function createNotification(
  input: Omit<ControlPlaneNotification, 'notificationId' | 'createdAt'> & {
    notificationId?: string;
    createdAt?: string;
  }
): ControlPlaneNotification {
  return {
    ...input,
    notificationId: input.notificationId ?? createId('ntf'),
    createdAt: input.createdAt ?? new Date().toISOString(),
  };
}

function createEvaluationSignal(
  accountId: string,
  input: ControlPlaneEvaluationSignalDraft & { signalId?: string; createdAt?: string }
): ControlPlaneEvaluationSignal {
  return {
    ...input,
    accountId,
    signalId: input.signalId ?? createId('eval'),
    createdAt: input.createdAt ?? new Date().toISOString(),
  };
}

export class ControlPlaneService {
  private pending = Promise.resolve();

  constructor(private readonly store: ControlPlaneStateStore) {}

  static create(
    statePath: string,
    databaseUrl?: string,
    options: {
      allowFileFallback?: boolean;
    } = {}
  ) {
    if (!databaseUrl && options.allowFileFallback === false) {
      throw new ControlPlaneConfigurationError(
        'DATABASE_URL is required for hosted control-plane PostgreSQL operations'
      );
    }

    const store = databaseUrl
      ? new PostgresControlPlaneStateStore({
          databaseUrl,
          seedStatePath: statePath,
        })
      : new FileControlPlaneStateStore(statePath);

    return new ControlPlaneService(store);
  }

  async listPlans() {
    return controlPlanePlanCatalog;
  }

  async health() {
    const state = await this.readState();
    const runtime = buildControlPlaneRuntimeSnapshot(this.store.kind);
    const counts = {
      accounts: Object.keys(state.accounts).length,
      users: Object.keys(state.users).length,
      devices: Object.keys(state.devices).length,
      deviceLinks: Object.keys(state.deviceLinks).length,
      ledgerEntries: state.ledger.length,
      evaluationSignals: state.evaluationSignals.length,
    };

    return {
      ok: true,
      service: 'elyan-control-plane',
      surface: runtime.surface,
      storage: runtime.storage,
      databaseConfigured: runtime.databaseConfigured,
      billingConfigured: runtime.billingConfigured,
      billingMode: runtime.billingMode,
      hostedReady: runtime.hostedReady,
      readiness: runtime.readiness,
      stateVersion: state.version,
      accountCount: counts.accounts,
      userCount: counts.users,
      deviceCount: counts.devices,
      deviceLinkCount: counts.deviceLinks,
      ledgerEntryCount: counts.ledgerEntries,
      counts,
      authConfigured: runtime.authConfigured,
      iyzicoConfigured: runtime.billingConfigured,
      runtime,
      connection: buildControlPlaneConnectionSnapshot(runtime),
    };
  }

  async getAccount(accountId: string) {
    const state = await this.readState();
    const account = state.accounts[accountId];

    if (!account) {
      throw new ControlPlaneNotFoundError('Account', accountId);
    }

    return buildAccountView(state, account);
  }

  async getIdentity(userId: string): Promise<ControlPlaneHostedSession> {
    const state = await this.readState();
    const user = state.users[userId];

    if (!user) {
      throw new ControlPlaneNotFoundError('Identity', userId);
    }

    const account = state.accounts[user.accountId];
    if (!account) {
      throw new ControlPlaneNotFoundError('Account', user.accountId);
    }

    return {
      userId: user.userId,
      email: user.email,
      name: user.displayName,
      accountId: account.accountId,
      ownerType: user.ownerType,
      role: user.role,
      planId: account.subscription.planId,
    };
  }

  async getIdentityByEmail(email: string): Promise<ControlPlaneHostedSession> {
    const normalizedEmail = normalizeIdentityEmail(email);
    const state = await this.readState();
    const user = Object.values(state.users).find((entry) => entry.email === normalizedEmail);

    if (!user) {
      throw new ControlPlaneNotFoundError('Identity', normalizedEmail);
    }

    return this.getIdentity(user.userId);
  }

  async registerIdentity(input: ControlPlaneIdentityRegisterInput) {
    return this.withState(async (state) => {
      const now = new Date().toISOString();
      const email = normalizeIdentityEmail(input.email);
      const duplicate = Object.values(state.users).find((user) => user.email === email);

      if (duplicate) {
        throw new ControlPlaneConflictError(`Identity already exists for ${email}`);
      }

      const userId = createId('usr');
      const accountId = createId('acct');
      const password = hashControlPlanePassword(input.password);

      const user: ControlPlaneUser = {
        userId,
        accountId,
        email,
        displayName: input.displayName,
        ownerType: input.ownerType,
        role: 'owner',
        passwordSalt: password.salt,
        passwordHash: password.hash,
        status: 'active',
        createdAt: now,
        updatedAt: now,
      };

      const account = createEmptyAccount(
        accountId,
        {
          displayName: input.displayName,
          ownerType: input.ownerType,
          planId: input.planId,
          ownerUserId: userId,
        },
        now
      );

      state.users[userId] = user;
      state.accounts[accountId] = account;
      state.notifications.push(
        createNotification({
          accountId,
          title: 'Account created',
          body: 'Your Elyan hosted account is ready. Install locally, then use this panel for billing, credits, and hosted access.',
          kind: 'product_notice',
          level: 'info',
          createdAt: now,
        })
      );

      await this.store.write(state);

      return {
        user: {
          userId: user.userId,
          accountId: user.accountId,
          email: user.email,
          displayName: user.displayName,
          ownerType: user.ownerType,
          role: user.role,
        },
        account: buildAccountView(state, account),
      };
    });
  }

  async authenticateIdentity(email: string, password: string) {
    const state = await this.readState();
    const normalizedEmail = normalizeIdentityEmail(email);
    const user = Object.values(state.users).find((entry) => entry.email === normalizedEmail);

    if (!user || user.status !== 'active') {
      return null;
    }

    if (!verifyControlPlanePassword(password, user.passwordSalt, user.passwordHash)) {
      return null;
    }

    return this.withState(async (mutableState) => {
      const nextUser = {
        ...user,
        lastLoginAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };

      mutableState.users[user.userId] = nextUser;
      await this.store.write(mutableState);

      const account = mutableState.accounts[user.accountId];
      if (!account) {
        throw new ControlPlaneNotFoundError('Account', user.accountId);
      }

      return {
        user: nextUser,
        account: buildAccountView(mutableState, account),
      };
    });
  }

  async upsertAccount(accountId: string, input: ControlPlaneAccountUpsertInput) {
    return this.withState(async (state) => {
      const now = new Date().toISOString();
      const existing = state.accounts[accountId];
      const nextAccount = existing ? this.reconcileAccount(existing, input, now) : createEmptyAccount(accountId, input, now);

      if (existing) {
        nextAccount.ownerUserId = input.ownerUserId ?? existing.ownerUserId;
        nextAccount.billingCustomerRef = input.billingCustomerRef ?? existing.billingCustomerRef;
        nextAccount.status = nextAccount.subscription.status;
      }

      state.accounts[accountId] = nextAccount;

      await this.store.write(state);
      return buildAccountView(state, nextAccount);
    });
  }

  async quoteUsage(accountId: string, input: ControlPlaneUsageInput): Promise<ControlPlaneUsageQuote> {
    const state = await this.readState();
    const account = state.accounts[accountId];

    if (!account) {
      throw new ControlPlaneNotFoundError('Account', accountId);
    }

    this.assertHostedUsageAllowed(account);

    const prepared = prepareUsageCharges(account, [input]);
    const charge = prepared.charges[0];
    const plan = getControlPlanePlan(account.subscription.planId);
    const usageSnapshot = normalizeUsageSnapshot(account.usageSnapshot, plan, account.balanceCredits);
    const denial = evaluateUsageConsumption(usageSnapshot, 1, 1, prepared.balanceBefore, prepared.balanceAfter);

    if (!charge) {
      throw new ControlPlaneValidationError('Usage quote requires at least one charge');
    }

    return {
      accountId,
      planId: account.subscription.planId,
      domain: input.domain,
      units: input.units,
      creditsDelta: formatCredits(charge.creditsDelta),
      balanceBefore: formatCredits(prepared.balanceBefore),
      balanceAfter: formatCredits(prepared.allowed ? prepared.balanceAfter : prepared.balanceBefore),
      allowed: prepared.allowed && denial.allowed,
      denialReason: denial.denialReason ?? (prepared.allowed ? undefined : 'monthly_credits_exhausted'),
      resetAt: denial.resetAt,
      remainingRequests: denial.remainingRequests,
      remainingHostedToolActionCalls: denial.remainingHostedToolActionCalls,
      monthlyCreditsRemaining: denial.monthlyCreditsRemaining,
    };
  }

  async recordUsage(accountId: string, input: ControlPlaneUsageInput) {
    const bundle = await this.recordUsageBundle(accountId, [input]);

    return {
      account: bundle.account,
      quote: bundle.quotes[0],
      ledgerEntry: bundle.ledgerEntries[0],
    };
  }

  async recordUsageBundle(accountId: string, inputs: ControlPlaneUsageInput[]) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];

      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      if (inputs.length === 0) {
        throw new ControlPlaneValidationError('Usage bundle requires at least one usage input');
      }

      this.assertHostedUsageAllowed(account);

      const plan = getControlPlanePlan(account.subscription.planId);
      const normalizedSnapshot = normalizeUsageSnapshot(account.usageSnapshot, plan, account.balanceCredits);
      const prepared = prepareUsageCharges(account, inputs);
      const now = new Date().toISOString();
      const allowance = evaluateUsageConsumption(
        normalizedSnapshot,
        1,
        inputs.length,
        prepared.balanceBefore,
        prepared.balanceAfter
      );

      if (!allowance.allowed) {
        const denial = describeUsageLimitDenial(allowance, plan);
        const denialEntries = prepared.charges.map((charge) =>
          createLedgerEntry({
            accountId,
            kind: 'usage_denial',
            status: 'denied',
            domain: charge.input.domain,
            creditsDelta: '0.00',
            balanceAfter: formatCredits(prepared.balanceBefore),
            source: charge.input.source,
            requestId: charge.input.requestId,
            note: charge.input.note ?? denial?.message ?? 'hosted usage denied',
            createdAt: now,
          })
        );

        state.ledger.push(...denialEntries);
        state.accounts[accountId] = {
          ...account,
          usageSnapshot: normalizedSnapshot,
          updatedAt: now,
        };
        await this.store.write(state);

        if (allowance.denialReason === 'monthly_credits_exhausted') {
          throw new ControlPlaneInsufficientCreditsError(
            denial?.message ?? `Insufficient credits for ${account.subscription.planId} on hosted usage bundle`,
            {
              monthlyCreditsRemaining: allowance.monthlyCreditsRemaining,
              balanceBefore: formatCredits(prepared.balanceBefore),
              balanceAfter: formatCredits(prepared.balanceAfter),
              planId: account.subscription.planId,
              requiredCredits: formatCredits(prepared.totalCreditsDelta),
            }
          );
        }

        throw new ControlPlaneUsageLimitError(
          denial?.message ?? `Hosted usage limit reached for ${account.subscription.planId}`,
          {
            limitType:
              allowance.denialReason === 'daily_tool_action_calls_limit'
                ? 'daily_tool_action_calls_limit'
                : 'daily_requests_limit',
            resetAt: allowance.resetAt,
            remainingRequests: allowance.remainingRequests,
            remainingHostedToolActionCalls: allowance.remainingHostedToolActionCalls,
            monthlyCreditsRemaining: allowance.monthlyCreditsRemaining,
            planId: account.subscription.planId,
          }
        );
      }

      let nextBalance = prepared.balanceBefore;
      const nextUsageTotals = { ...account.usageTotals };
      const ledgerEntries = prepared.charges.map((charge) => {
        const creditsDelta = formatCredits(charge.creditsDelta);
        nextBalance = nextBalance.minus(creditsDelta);
        nextUsageTotals[charge.input.domain] = addCredits(nextUsageTotals[charge.input.domain], creditsDelta);

        return createLedgerEntry({
          accountId,
          kind: 'usage_charge',
          status: 'posted',
          domain: charge.input.domain,
          creditsDelta: `-${creditsDelta}`,
          balanceAfter: formatCredits(nextBalance),
          source: charge.input.source,
          requestId: charge.input.requestId,
          note: charge.input.note,
          createdAt: now,
        });
      });

      const nextAccount: ControlPlaneAccount = {
        ...account,
        balanceCredits: formatCredits(nextBalance),
        usageTotals: nextUsageTotals,
        usageSnapshot: advanceUsageSnapshot(normalizedSnapshot, plan, nextBalance, 1, inputs.length, new Date(now)),
        updatedAt: now,
      };

      state.accounts[accountId] = nextAccount;
      state.ledger.push(...ledgerEntries);
      await this.store.write(state);

      let runningBalance = prepared.balanceBefore;
      const quotes = prepared.charges.map((charge) => {
        const creditsDelta = formatCredits(charge.creditsDelta);
        runningBalance = runningBalance.minus(creditsDelta);

        return {
          accountId,
          planId: nextAccount.subscription.planId,
          domain: charge.input.domain,
          units: charge.input.units,
          creditsDelta,
          balanceBefore: formatCredits(
            runningBalance.plus(creditsDelta)
          ),
          balanceAfter: formatCredits(runningBalance),
          allowed: true,
        };
      });

      return {
        account: buildAccountView(state, nextAccount),
        quotes,
        ledgerEntries,
      };
    });
  }

  async recordEvaluationSignal(accountId: string, input: ControlPlaneEvaluationSignalDraft) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];

      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      this.assertHostedImprovementAllowed(account);

      if (input.requestId) {
        const existing = state.evaluationSignals.find(
          (signal) => signal.accountId === accountId && signal.requestId === input.requestId
        );

        if (existing) {
          return existing;
        }
      }

      const signal = createEvaluationSignal(accountId, input);
      state.evaluationSignals.push(signal);
      await this.store.write(state);

      return signal;
    });
  }

  async listLedger(accountId: string, limit = 25) {
    const state = await this.readState();
    return state.ledger.filter((entry) => entry.accountId === accountId).slice(-limit).reverse();
  }

  async listNotifications(accountId: string, limit = 25) {
    const state = await this.readState();
    return state.notifications.filter((entry) => entry.accountId === accountId).slice(-limit).reverse();
  }

  async listDevices(accountId: string, limit = 25) {
    const state = await this.readState();
    return Object.values(state.devices)
      .filter((device) => device.accountId === accountId)
      .slice(-limit)
      .reverse();
  }

  async markNotificationSeen(accountId: string, notificationId: string) {
    return this.withState(async (state) => {
      const notification = state.notifications.find(
        (entry) => entry.accountId === accountId && entry.notificationId === notificationId
      );

      if (!notification) {
        throw new ControlPlaneNotFoundError('Notification', notificationId);
      }

      notification.seenAt = notification.seenAt ?? new Date().toISOString();
      await this.store.write(state);
      return notification;
    });
  }

  async startDeviceLink(accountId: string, userId: string, input: ControlPlaneDeviceLinkStartInput) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];
      const user = state.users[userId];

      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      if (!user || user.accountId !== accountId) {
        throw new ControlPlaneAuthenticationError('Device linking requires the signed-in account owner');
      }

      const now = new Date().toISOString();
      const linkCode = createId('lnk');
      const link: ControlPlaneDeviceLink = {
        linkCode,
        accountId,
        userId,
        deviceLabel: input.deviceLabel,
        status: 'pending',
        expiresAt: new Date(Date.parse(now) + 15 * 60 * 1000).toISOString(),
        createdAt: now,
      };

      state.deviceLinks[linkCode] = link;
      await this.store.write(state);

      return link;
    });
  }

  async completeDeviceLink(input: ControlPlaneDeviceLinkCompleteInput) {
    return this.withState(async (state) => {
      const now = new Date().toISOString();
      const link = state.deviceLinks[input.linkCode];

      if (!link) {
        throw new ControlPlaneNotFoundError('Device link', input.linkCode);
      }

      if (link.status !== 'pending') {
        throw new ControlPlaneConflictError(`Device link is ${link.status}`);
      }

      if (Date.parse(link.expiresAt) <= Date.parse(now)) {
        link.status = 'expired';
        await this.store.write(state);
        throw new ControlPlaneConflictError('Device link has expired');
      }

      const account = state.accounts[link.accountId];
      const user = state.users[link.userId];
      if (!account || !user) {
        throw new ControlPlaneNotFoundError('Account', link.accountId);
      }

      const deviceId = createId('dev');
      const deviceToken = `devtok_${randomUUID().replace(/-/g, '')}`;
      const device: ControlPlaneDevice = {
        deviceId,
        accountId: account.accountId,
        userId: user.userId,
        deviceLabel: input.deviceLabel,
        status: 'active',
        deviceToken,
        metadata: { ...(input.metadata ?? {}) },
        linkedAt: now,
        createdAt: now,
        updatedAt: now,
        lastSeenAt: now,
      };

      link.status = 'complete';
      link.completedAt = now;
      link.consumedAt = now;
      link.deviceToken = deviceToken;
      link.deviceLabel = input.deviceLabel;

      state.devices[deviceId] = device;
      state.deviceLinks[link.linkCode] = link;
      state.notifications.push(
        createNotification({
          accountId: account.accountId,
          title: 'Device linked',
          body: `${input.deviceLabel} is now linked to this Elyan account.`,
          kind: 'product_notice',
          level: 'info',
          createdAt: now,
        })
      );

      await this.store.write(state);

      return {
        link,
        device,
      };
    });
  }

  async bootstrapDevice(deviceToken: string) {
    const state = await this.readState();
    const device = this.findDeviceByToken(state, deviceToken);

    if (!device) {
      throw new ControlPlaneNotFoundError('Device', deviceToken);
    }

    if (device.status !== 'active') {
      throw new ControlPlaneEntitlementError(`Device is ${device.status}`);
    }

    const account = state.accounts[device.accountId];
    if (!account) {
      throw new ControlPlaneNotFoundError('Account', device.accountId);
    }

    const release = await this.getLatestReleaseSnapshot().catch(() => null);

    return {
      ok: true,
      device,
      account: buildAccountView(state, account),
      ledger: state.ledger.filter((entry) => entry.accountId === account.accountId).slice(-20).reverse(),
      release,
      syncScope: {
        accountId: account.accountId,
        planId: account.subscription.planId,
        entitlements: account.entitlements,
        usageTotals: account.usageTotals,
      },
    };
  }

  async pushDevice(input: ControlPlaneDevicePushInput) {
    return this.withState(async (state) => {
      const device = this.findDeviceByToken(state, input.deviceToken);

      if (!device) {
        throw new ControlPlaneNotFoundError('Device', input.deviceToken);
      }

      if (device.status !== 'active') {
        throw new ControlPlaneEntitlementError(`Device is ${device.status}`);
      }

      const now = new Date().toISOString();
      const nextDevice: ControlPlaneDevice = {
        ...device,
        metadata: { ...device.metadata, ...(input.metadata ?? {}) },
        lastSeenReleaseTag: input.lastSeenReleaseTag ?? device.lastSeenReleaseTag,
        lastSeenAt: now,
        updatedAt: now,
      };

      state.devices[device.deviceId] = nextDevice;
      await this.store.write(state);

      return {
        ok: true,
        device: nextDevice,
        release: await this.getLatestReleaseSnapshot().catch(() => null),
      };
    });
  }

  async unlinkDevice(deviceToken: string) {
    return this.withState(async (state) => {
      const device = this.findDeviceByToken(state, deviceToken);

      if (!device) {
        throw new ControlPlaneNotFoundError('Device', deviceToken);
      }

      const now = new Date().toISOString();
      const nextDevice: ControlPlaneDevice = {
        ...device,
        status: 'revoked',
        revokedAt: now,
        updatedAt: now,
      };

      state.devices[device.deviceId] = nextDevice;

      for (const link of Object.values(state.deviceLinks)) {
        if (link.deviceToken === deviceToken) {
          link.status = 'consumed';
          link.consumedAt = link.consumedAt ?? now;
        }
      }

      await this.store.write(state);

      return {
        ok: true,
        device: nextDevice,
      };
    });
  }

  async ensureIyzicoBillingBinding(accountId: string) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];
      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      const plan = getControlPlanePlan(account.subscription.planId);
      if (!plan.entitlements.hostedAccess) {
        throw new ControlPlaneEntitlementError(
          `Billing binding is not available for plan ${account.subscription.planId}`
        );
      }

      const client = getIyzicoBillingClient();
      if (!client.isConfigured()) {
        throw new ControlPlaneConfigurationError(
          'Iyzico API credentials are required to initialize hosted billing'
        );
      }

      if (!account.ownerUserId) {
        throw new ControlPlaneEntitlementError('Hosted billing initialization requires a bound owner identity');
      }

      const owner = state.users[account.ownerUserId];
      if (!owner) {
        throw new ControlPlaneNotFoundError('Identity', account.ownerUserId);
      }

      const nextBinding = await this.ensurePlanBinding(state, plan.id);
      const customerReferenceCode = account.billingCustomerRef ?? account.accountId;
      const callbackUrl = buildControlPlaneRuntimeSnapshot(this.store.kind).callbackUrl;
      const ownerName = splitDisplayName(owner.displayName);
      const initializationAlreadyBound =
        account.subscription.provider === 'iyzico' &&
        (account.subscription.syncState === 'pending' || account.subscription.syncState === 'synced') &&
        Boolean(account.subscription.providerPricingPlanRef || account.subscription.providerProductRef);

      if (initializationAlreadyBound) {
        state.billing.iyzico.plans[plan.id] = nextBinding;
        state.accounts[accountId] = {
          ...account,
          billingCustomerRef: customerReferenceCode,
          subscription: {
            ...account.subscription,
            providerCustomerRef:
              account.subscription.providerCustomerRef ?? customerReferenceCode,
            providerProductRef:
              account.subscription.providerProductRef ?? nextBinding.productReferenceCode,
            providerPricingPlanRef:
              account.subscription.providerPricingPlanRef ?? nextBinding.pricingPlanReferenceCode,
            providerStatus:
              account.subscription.providerStatus ??
              (account.subscription.syncState === 'pending' ? 'PENDING' : undefined),
            lastSyncedAt: account.subscription.lastSyncedAt ?? new Date().toISOString(),
          },
          entitlements: resolveEntitlements(plan, account.subscription),
          status: account.subscription.status,
          updatedAt: new Date().toISOString(),
        };
        await this.store.write(state);

        return {
          account: buildAccountView(state, state.accounts[accountId]),
          binding: nextBinding,
          initialization: null,
          reusedInitialization: true,
        };
      }

      const init = await client.initializeSubscription({
        plan,
        pricingPlanReferenceCode: nextBinding.pricingPlanReferenceCode ?? '',
        callbackUrl,
        conversationId: account.accountId,
        customer: {
          name: ownerName.name,
          surname: ownerName.surname,
          email: owner.email,
        },
      });

      state.billing.iyzico.plans[plan.id] = nextBinding;
      state.accounts[accountId] = {
        ...account,
        billingCustomerRef: customerReferenceCode,
        subscription: {
          ...account.subscription,
          provider: 'iyzico',
          providerCustomerRef: customerReferenceCode,
          syncState: 'pending',
          providerProductRef: nextBinding.productReferenceCode,
          providerPricingPlanRef: nextBinding.pricingPlanReferenceCode,
          providerStatus: 'PENDING',
          lastSyncedAt: new Date().toISOString(),
          lastSyncError: undefined,
        },
        entitlements: resolveEntitlements(plan, {
          ...account.subscription,
          provider: 'iyzico',
          syncState: 'pending',
        }),
        status: 'trialing',
        updatedAt: new Date().toISOString(),
      };
      state.notifications.push(
        createNotification({
          accountId,
          title: 'Billing session started',
          body: `Hosted billing initialization started for ${plan.title}. Complete checkout to activate hosted credits and entitlements.`,
          kind: 'billing_notice',
          level: 'info',
        })
      );

      await this.store.write(state);

      return {
        account: buildAccountView(state, state.accounts[accountId]),
        binding: nextBinding,
        initialization: init,
        reusedInitialization: false,
      };
    });
  }

  async applyIyzicoWebhook(
    payload: IyzicoSubscriptionWebhook,
    signatureHeader?: string | null,
    options?: { bypassSignatureValidation?: boolean }
  ) {
    return this.withState(async (state) => {
      const client = getIyzicoBillingClient();
      if (!options?.bypassSignatureValidation && !client.verifyWebhook(payload, signatureHeader)) {
        throw new ControlPlaneAuthenticationError('Invalid iyzico webhook signature');
      }

      const now = new Date().toISOString();
      const account = this.findAccountForIyzicoWebhook(state, payload);
      const eventRef = buildIyzicoWebhookEventRef(payload);

      if (!account) {
        throw new ControlPlaneNotFoundError(
          'Account',
          payload.subscriptionReferenceCode ?? payload.customerReferenceCode
        );
      }

      if (account.subscription.processedWebhookEventRefs.includes(eventRef)) {
        return {
          account: buildAccountView(state, account),
          ledgerEntry: undefined,
          applied: false,
          duplicate: true,
          webhookEventRef: eventRef,
        };
      }

      const plan = getControlPlanePlan(account.subscription.planId);
      const nextSubscription = {
        ...account.subscription,
        provider: 'iyzico' as const,
        providerCustomerRef: payload.customerReferenceCode ?? account.subscription.providerCustomerRef,
        providerSubscriptionRef:
          payload.subscriptionReferenceCode ?? account.subscription.providerSubscriptionRef,
        providerStatus: payload.iyziEventType,
        lastSyncedAt: now,
        processedWebhookEventRefs: appendProcessedWebhookEventRef(
          account.subscription.processedWebhookEventRefs,
          eventRef
        ),
      };

      let nextBalance = new Decimal(account.balanceCredits);
      let ledgerEntry: ControlPlaneLedgerEntry | undefined;

      if (payload.iyziEventType === 'subscription.order.success') {
        const topUp = getHostedBalanceTopUp(account, account.subscription.planId);
        const grantedCredits = topUp.greaterThan(0) ? topUp : new Decimal(0);
        nextSubscription.status = 'active';
        nextSubscription.syncState = 'synced';
        nextSubscription.retryCount = 0;
        nextSubscription.nextRetryAt = undefined;
        nextSubscription.lastSyncError = undefined;
        nextSubscription.currentPeriodStartedAt = now;
        nextSubscription.currentPeriodEndsAt = new Date(
          Date.parse(now) + THIRTY_DAYS_MS
        ).toISOString();
        nextSubscription.creditsGrantedThisPeriod = formatCredits(grantedCredits);
        if (grantedCredits.greaterThan(0)) {
          nextBalance = nextBalance.plus(grantedCredits);
          ledgerEntry = createLedgerEntry({
            accountId: account.accountId,
            kind: 'subscription_grant',
            status: 'posted',
            creditsDelta: formatCredits(grantedCredits),
            balanceAfter: formatCredits(nextBalance),
            source: 'hosted_api',
            note: `iyzico activation for ${account.subscription.planId}`,
            createdAt: now,
          });
        }
        state.notifications.push(
          createNotification({
            accountId: account.accountId,
            title: 'Subscription active',
            body: `Hosted subscription for ${plan.title} is active. Credits and hosted entitlements are now available.`,
            kind: 'billing_notice',
            level: 'info',
            createdAt: now,
          })
        );
      } else {
        const retryCount = account.subscription.retryCount + 1;
        nextSubscription.retryCount = retryCount;
        nextSubscription.syncState = 'failed';
        nextSubscription.status = retryCount >= 3 ? 'suspended' : 'past_due';
        nextSubscription.nextRetryAt =
          retryCount >= 3 ? undefined : new Date(Date.parse(now) + BILLING_RETRY_WINDOW_MS).toISOString();
        nextSubscription.lastSyncError = `iyzico webhook ${payload.iyziEventType} for ${payload.subscriptionReferenceCode} (retry ${retryCount}/3)`;
        state.notifications.push(
          createNotification({
            accountId: account.accountId,
            title: 'Subscription attention required',
            body: `Hosted billing reported ${payload.iyziEventType}. Subscription state is now ${nextSubscription.status}.`,
            kind: 'entitlement_notice',
            level: retryCount >= 3 ? 'error' : 'warning',
            createdAt: now,
          })
        );
      }

      const nextAccount: ControlPlaneAccount = {
        ...account,
        status: nextSubscription.status,
        subscription: nextSubscription,
        entitlements: resolveEntitlements(plan, nextSubscription),
        balanceCredits: formatCredits(nextBalance),
        updatedAt: now,
      };

      state.accounts[account.accountId] = nextAccount;
      if (ledgerEntry) {
        state.ledger.push(ledgerEntry);
      }

      await this.store.write(state);

      return {
        account: buildAccountView(state, nextAccount),
        ledgerEntry,
        applied: true,
        duplicate: false,
        webhookEventRef: eventRef,
      };
    });
  }

  async getLatestReleaseSnapshot() {
    const { getLatestElyanReleaseSnapshot } = await import('./releases');
    return getLatestElyanReleaseSnapshot();
  }

  private async readState(): Promise<ControlPlaneState> {
    return this.store.read();
  }

  private reconcileAccount(
    account: ControlPlaneAccount,
    input: ControlPlaneAccountUpsertInput,
    updatedAt: string
  ): ControlPlaneAccount {
    const nextPlan = getControlPlanePlan(input.planId);
    const nextBalance = nextPlan.entitlements.hostedAccess ? new Decimal(account.balanceCredits) : new Decimal('0.00');
    const nextSubscription = reconcileSubscription(
      account,
      input.planId,
      updatedAt,
      input.billingCustomerRef ?? account.billingCustomerRef
    );
    const planChanged = account.subscription.planId !== nextPlan.id;
    const nextUsageSnapshot = planChanged
      ? createAccountUsageSnapshot(nextPlan, nextBalance, new Date(updatedAt), {
          dailyRequests: 0,
          dailyHostedToolActionCalls: 0,
        })
      : normalizeUsageSnapshot(account.usageSnapshot, nextPlan, nextBalance, new Date(updatedAt));

    return {
      ...account,
      displayName: input.displayName,
      ownerType: input.ownerType,
      ownerUserId: input.ownerUserId ?? account.ownerUserId,
      billingCustomerRef: nextPlan.entitlements.hostedAccess ? input.billingCustomerRef ?? account.billingCustomerRef : undefined,
      status: nextSubscription.status,
      subscription: nextSubscription,
      entitlements: resolveEntitlements(nextPlan, nextSubscription),
      balanceCredits: formatCredits(nextBalance),
      usageSnapshot: nextUsageSnapshot,
      updatedAt,
    };
  }

  private async withState<T>(operation: (state: ControlPlaneState) => Promise<T>) {
    const run = this.pending.then(async () => {
      const state = await this.store.read();
      return operation(state);
    });

    this.pending = run.then(
      () => undefined,
      () => undefined
    );

    return run;
  }

  private findDeviceByToken(state: ControlPlaneState, deviceToken: string) {
    return Object.values(state.devices).find((device) => device.deviceToken === deviceToken);
  }

  private assertHostedUsageAllowed(account: ControlPlaneAccount) {
    if (!account.entitlements.hostedAccess || !account.entitlements.hostedUsageAccounting) {
      throw new ControlPlaneEntitlementError(
        `Hosted usage is disabled for plan ${account.subscription.planId}`
      );
    }

    if (!isHostedBillingReady(account.subscription)) {
      throw new ControlPlaneEntitlementError(
        `Hosted usage is not active for subscription status ${account.subscription.status}`
      );
    }
  }

  private assertHostedImprovementAllowed(account: ControlPlaneAccount) {
    if (!account.entitlements.hostedImprovementSignals) {
      throw new ControlPlaneEntitlementError(
        `Hosted improvement signals are disabled for plan ${account.subscription.planId}`
      );
    }

    if (!isHostedBillingReady(account.subscription)) {
      throw new ControlPlaneEntitlementError(
        `Hosted improvement signals are not active for subscription status ${account.subscription.status}`
      );
    }
  }

  private async ensurePlanBinding(state: ControlPlaneState, planId: ControlPlaneAccount['subscription']['planId']) {
    const plan = getControlPlanePlan(planId);
    const existing = state.billing.iyzico.plans[planId];

    if (
      existing &&
      existing.syncState === 'synced' &&
      existing.productReferenceCode &&
      existing.pricingPlanReferenceCode
    ) {
      return existing;
    }

    const binding = existing ?? buildIyzicoPlanBinding(plan);
    const client = getIyzicoBillingClient();
    const productName = binding.productName || `Elyan ${plan.title}`;
    const pricingPlanName = binding.pricingPlanName || `${plan.title} Monthly`;

    let productReferenceCode = binding.productReferenceCode;
    if (!productReferenceCode) {
      productReferenceCode = await client.findProductReferenceCodeByName(productName);
    }

    if (!productReferenceCode) {
      const product = await client.ensureProduct(plan);
      productReferenceCode = product.productReferenceCode;
    }

    if (!productReferenceCode) {
      throw new ControlPlaneProviderError(`Iyzico did not return a product reference code for ${planId}`);
    }

    let pricingPlanReferenceCode = binding.pricingPlanReferenceCode;
    if (!pricingPlanReferenceCode && productReferenceCode) {
      pricingPlanReferenceCode = await client.findPricingPlanReferenceCodeByName(
        productReferenceCode,
        pricingPlanName
      );
    }

    if (!pricingPlanReferenceCode) {
      const pricingPlan = await client.ensurePricingPlan(plan, productReferenceCode);
      pricingPlanReferenceCode = pricingPlan.pricingPlanReferenceCode;
    }

    if (!pricingPlanReferenceCode) {
      throw new ControlPlaneProviderError(`Iyzico did not return a pricing plan reference code for ${planId}`);
    }

    const nextBinding: ControlPlaneBillingPlanBinding = {
      ...binding,
      productName,
      pricingPlanName,
      productReferenceCode: productReferenceCode || undefined,
      pricingPlanReferenceCode: pricingPlanReferenceCode || undefined,
      currencyCode: 'TRY',
      paymentInterval: 'MONTHLY',
      paymentIntervalCount: 1,
      planPaymentType: 'RECURRING',
      syncState: productReferenceCode && pricingPlanReferenceCode ? 'synced' : 'pending',
      lastSyncedAt: new Date().toISOString(),
      lastSyncError: undefined,
    };

    if (!nextBinding.productReferenceCode || !nextBinding.pricingPlanReferenceCode) {
      throw new ControlPlaneProviderError(`Iyzico did not return plan references for ${planId}`);
    }

    state.billing.iyzico.plans[planId] = nextBinding;
    return nextBinding;
  }

  private findAccountForIyzicoWebhook(
    state: ControlPlaneState,
    payload: IyzicoSubscriptionWebhook
  ) {
    const bySubscription = Object.values(state.accounts).find(
      (account) => account.subscription.providerSubscriptionRef === payload.subscriptionReferenceCode
    );

    if (bySubscription) {
      return bySubscription;
    }

    const byCustomer = Object.values(state.accounts).find(
      (account) =>
        account.subscription.providerCustomerRef === payload.customerReferenceCode ||
        account.billingCustomerRef === payload.customerReferenceCode
    );

    if (byCustomer) {
      return byCustomer;
    }

    return undefined;
  }
}
