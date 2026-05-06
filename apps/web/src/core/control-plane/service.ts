/**
 * Hosted control-plane domain service.
 * Layer: control-plane. Critical orchestrator for auth, accounts, billing, devices, integrations, and panel state.
 */
import { randomUUID } from 'crypto';
import Decimal from 'decimal.js';
import { z } from 'zod';
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
import { buildControlPlaneEvaluationSummary } from './evaluation';
import { buildAccountPolicySnapshot, buildHostedConnectionRegistry } from './governance';
import { buildControlPlaneDatabaseHealthSnapshot, getControlPlanePool, getControlPlanePoolStats } from './database';
import { readCanonicalSharedTruthSnapshot } from './migrations';
import { getRuntimeVersionInfo } from '@/core/runtime-version';
import {
  buildLearningArtifacts,
  buildLearningRetrievalText,
  deriveLearningSignal,
  persistLearningArtifacts,
} from './learning/signal-extractor';
import { buildMemoryContext } from '@/core/memory';
import { ingestRetrievalText, searchRetrievalDocumentsHybrid } from '@/core/retrieval';
import { filterContextBlocks } from '@/core/retrieval/context';
import { FileControlPlaneStateStore, type ControlPlaneStateStore } from './store';
import { PostgresControlPlaneStateStore } from './postgres-store';
import { evaluateReasoningOutcome } from '@/core/reasoning';
import type { OrchestrationPlan } from '@/core/orchestration';
import {
  advanceUsageSnapshot,
  createUsageSnapshot,
  describeUsageLimitDenial,
  evaluateUsageConsumption,
  normalizeUsageSnapshot,
} from './usage';
import {
  buildIntegrationRedirectUri,
  decryptIntegrationSecret,
  encryptIntegrationSecret,
  exchangeOAuthCode,
  fetchIntegrationProfile,
  getIntegrationProviderConfig,
  isIntegrationProviderConfigured,
  refreshOAuthToken,
} from './integration-provider';
import type { SearchMode } from '@/types/search';
import type {
  ControlPlaneAccount,
  ControlPlaneAccountUpsertInput,
  ControlPlaneAccountPublic,
  ControlPlaneBillingPlanBinding,
  ControlPlaneConversationMessage,
  ControlPlaneConversationThread,
  ControlPlaneEvaluationSignal,
  ControlPlaneEvaluationSignalDraft,
  ControlPlaneDevice,
  ControlPlaneDeviceLink,
  ControlPlaneDeviceLinkCompleteInput,
  ControlPlaneDeviceLinkStartInput,
  ControlPlaneDevicePushInput,
  ControlPlaneEntitlements,
  ControlPlaneInteractionIntent,
  ControlPlaneInteractionState,
  ControlPlaneHostedDevice,
  ControlPlaneHostedSession,
  ControlPlaneLedgerEntry,
  ControlPlaneLearningDraft,
  ControlPlaneLearningEvent,
  ControlPlaneTaskIntent,
  ControlPlaneMemoryItem,
  ControlPlaneNotification,
  ControlPlaneIntegration,
  ControlPlaneIntegrationProvider,
  ControlPlaneIntegrationPublic,
  ControlPlaneIntegrationActionInput,
  ControlPlaneIntegrationCallbackInput,
  ControlPlaneIntegrationConnectStartInput,
  ControlPlaneIntegrationDisconnectInput,
  ControlPlaneState,
  ControlPlaneUsageInput,
  ControlPlaneUsageQuote,
  ControlPlaneIdentityRegisterInput,
  ControlPlaneUser,
} from './types';
import { controlPlaneTaskIntentSchema } from './types';
import { buildInteractionThreadTitle, buildMemorySummary, deriveMemoryKind } from '@/core/interaction/intent';

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
    integrations: {},
    interactionState: createEmptyInteractionState(),
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

function createEmptyInteractionState(): ControlPlaneInteractionState {
  return {
    threads: [],
    messages: [],
    memoryItems: [],
    learningDrafts: [],
  };
}

function normalizeInteractionState(state?: ControlPlaneInteractionState | null) {
  return state ?? createEmptyInteractionState();
}

function createInteractionId(prefix: string) {
  return `${prefix}_${randomUUID().replace(/-/g, '')}`;
}

function trimInteractionHistory<T>(items: T[], limit: number) {
  return items.length > limit ? items.slice(-limit) : items;
}

function summarizeInteractionThread(query: string, responseText?: string) {
  const parts = [query.trim(), responseText?.trim()].filter(Boolean);
  return buildMemorySummary(parts.join(' | '), 280);
}

function createInteractionMessage(
  threadId: string,
  accountId: string,
  role: ControlPlaneConversationMessage['role'],
  content: string,
  source: string,
  metadata?: Record<string, unknown>
): ControlPlaneConversationMessage {
  return {
    messageId: createInteractionId('msg'),
    threadId,
    accountId,
    role,
    content,
    source,
    createdAt: new Date().toISOString(),
    metadata: metadata ?? {},
  };
}

function createInteractionThread(
  accountId: string,
  source: string,
  intent: ControlPlaneInteractionIntent,
  title: string,
  summary: string,
  metadata?: Record<string, unknown>,
  threadId?: string
): ControlPlaneConversationThread {
  const now = new Date().toISOString();

  return {
    threadId: threadId ?? createInteractionId('thr'),
    accountId,
    source,
    title,
    summary,
    intent,
    status: 'active',
    messageCount: 0,
    createdAt: now,
    updatedAt: now,
    metadata: metadata ?? {},
  };
}

function createInteractionMemoryItem(
  accountId: string,
  kind: ControlPlaneMemoryItem['kind'],
  title: string,
  summary: string,
  source: ControlPlaneMemoryItem['source'],
  options?: {
    threadId?: string;
    projectKey?: string;
    routineKey?: string;
    confidence?: number;
    pinned?: boolean;
    promoted?: boolean;
    promotedFromDraftId?: string;
    metadata?: Record<string, unknown>;
  }
): ControlPlaneMemoryItem {
  const now = new Date().toISOString();

  return {
    memoryId: createInteractionId('mem'),
    accountId,
    kind,
    title,
    summary,
    source,
    threadId: options?.threadId,
    projectKey: options?.projectKey,
    routineKey: options?.routineKey,
    confidence: options?.confidence ?? 0.7,
    pinned: options?.pinned ?? false,
    promoted: options?.promoted ?? false,
    promotedFromDraftId: options?.promotedFromDraftId,
    createdAt: now,
    updatedAt: now,
    metadata: options?.metadata ?? {},
  };
}

function createLearningDraft(
  accountId: string,
  kind: ControlPlaneLearningDraft['kind'],
  title: string,
  summary: string,
  body: string,
  source: string,
  options?: {
    threadId?: string;
    promotedMemoryId?: string;
    metadata?: Record<string, unknown>;
  }
): ControlPlaneLearningDraft {
  const now = new Date().toISOString();

  return {
    draftId: createInteractionId('ldr'),
    accountId,
    threadId: options?.threadId,
    kind,
    title,
    summary,
    body,
    status: 'draft',
    promotedMemoryId: options?.promotedMemoryId,
    source,
    createdAt: now,
    updatedAt: now,
    metadata: options?.metadata ?? {},
  };
}

type InteractionContextInput = {
  query: string;
  source: string;
  conversationId?: string;
  threadId?: string;
};

type InteractionRecordInput = {
  source: string;
  query: string;
  responseText: string;
  mode: SearchMode;
  intent: ControlPlaneInteractionIntent;
  confidence: 'low' | 'medium' | 'high';
  conversationId?: string;
  messageId?: string;
  userId?: string;
  displayName?: string;
  modelId?: string;
  threadTitle?: string;
  metadata?: Record<string, unknown>;
  sources?: Array<{ url: string; title: string }>;
  citationCount?: number;
};

type LearningEventRecordInput = {
  requestId: string;
  source: string;
  input: string;
  intent: ControlPlaneInteractionIntent;
  taskType?: ControlPlaneTaskIntent;
  spaceId?: string;
  plan: string;
  reasoningSteps?: string[];
  output?: string;
  betterOutput?: string;
  success: boolean;
  failureReason?: string;
  feedback?: Record<string, unknown>;
  latencyMs: number;
  score?: number;
  accepted?: boolean;
  modelId?: string;
  modelProvider?: string;
  isSafeForLearning?: boolean;
  metadata?: Record<string, unknown>;
};

function resolveLearningTaskType(input: Pick<LearningEventRecordInput, 'intent' | 'taskType' | 'metadata'>) {
  if (input.taskType) {
    return input.taskType;
  }

  const candidate =
    (typeof input.metadata?.task_type === 'string' ? input.metadata.task_type : undefined) ??
    (typeof input.metadata?.taskIntent === 'string' ? input.metadata.taskIntent : undefined) ??
    input.intent;

  const parsed = controlPlaneTaskIntentSchema.safeParse(candidate);
  return parsed.success ? parsed.data : 'direct_answer';
}

function resolveLearningSpaceId(accountId: string, input: Pick<LearningEventRecordInput, 'spaceId' | 'metadata'>) {
  const metadataSpaceId =
    typeof input.metadata?.space_id === 'string'
      ? input.metadata.space_id
      : typeof input.metadata?.spaceId === 'string'
        ? input.metadata.spaceId
        : undefined;

  return input.spaceId?.trim() || metadataSpaceId?.trim() || accountId;
}

type PreparedUsageCharge = {
  input: ControlPlaneUsageInput;
  rate: Decimal;
  creditsDelta: Decimal;
};

type DeviceSummary = {
  total: number;
  pending: number;
  active: number;
  revoked: number;
  expired: number;
};

function buildHostedDevice(device: ControlPlaneDevice): ControlPlaneHostedDevice {
  return {
    deviceId: device.deviceId,
    deviceLabel: device.deviceLabel,
    status: device.status,
    linkedAt: device.linkedAt,
    lastSeenAt: device.lastSeenAt,
    lastSeenReleaseTag: device.lastSeenReleaseTag,
    revokedAt: device.revokedAt,
    createdAt: device.createdAt,
    updatedAt: device.updatedAt,
  };
}

function sanitizeIntegration(integration: ControlPlaneIntegration): ControlPlaneIntegrationPublic {
  const { accessTokenCiphertext: _accessTokenCiphertext, refreshTokenCiphertext: _refreshTokenCiphertext, idTokenCiphertext: _idTokenCiphertext, ...publicIntegration } = integration;
  void _accessTokenCiphertext;
  void _refreshTokenCiphertext;
  void _idTokenCiphertext;
  return publicIntegration;
}

function buildIntegrationSummary(integrations: Record<string, ControlPlaneIntegration>) {
  const publicIntegrations = Object.values(integrations).map((integration) => sanitizeIntegration(integration));
  const connected = publicIntegrations.filter((integration) => integration.status === 'connected').length;
  const needsAttention = publicIntegrations.filter(
    (integration) => integration.status === 'expired' || integration.status === 'error'
  ).length;

  return {
    total: publicIntegrations.length,
    connected,
    needsAttention,
    items: Object.fromEntries(
      publicIntegrations.map((integration) => [integration.integrationId, integration])
    ),
  };
}

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

function countAccountDeviceStates(state: ControlPlaneState, accountId: string): DeviceSummary {
  return Object.values(state.devices)
    .filter((device) => device.accountId === accountId)
    .reduce<DeviceSummary>(
      (summary, device) => {
        summary.total += 1;
        summary[device.status] += 1;
        return summary;
      },
      {
        total: 0,
        pending: 0,
        active: 0,
        revoked: 0,
        expired: 0,
      }
    );
}

function buildAccountView(state: ControlPlaneState, account: ControlPlaneAccount): ControlPlaneAccountPublic & {
  plan: ReturnType<typeof getControlPlanePlan>;
  processedWebhookEventCount: number;
  deviceSummary: DeviceSummary;
  integrationSummary: { total: number; connected: number; needsAttention: number };
  interactionSummary: {
    threadCount: number;
    messageCount: number;
    memoryItemCount: number;
    learningDraftCount: number;
  };
  recentLedgerEntries: ControlPlaneLedgerEntry[];
  recentEvaluationSignals: ControlPlaneEvaluationSignal[];
  evaluationSignalCount: number;
  recentNotifications: ControlPlaneNotification[];
  recentDevices: ControlPlaneHostedDevice[];
  recentLearningDrafts: ControlPlaneLearningDraft[];
  learningEventCount: number;
  policySnapshot: ReturnType<typeof buildAccountPolicySnapshot>;
  connectionRegistry: ReturnType<typeof buildHostedConnectionRegistry>;
} {
  const accountEvaluationSignals = state.evaluationSignals.filter(
    (signal) => signal.accountId === account.accountId
  );
  const accountLearningEvents = state.learningEvents.filter((event) => event.accountId === account.accountId);
  const recentEvaluationSignals = accountEvaluationSignals.slice(-10).reverse();
  const plan = getControlPlanePlan(account.subscription.planId);
  const usageSnapshot = normalizeUsageSnapshot(account.usageSnapshot, plan, account.balanceCredits);
  const deviceSummary = countAccountDeviceStates(state, account.accountId);
  const interactionState = normalizeInteractionState(account.interactionState);
  const recentNotifications = state.notifications
    .filter((notification) => notification.accountId === account.accountId)
    .slice(-5)
    .reverse();
  const connectedDevices = Object.values(state.devices)
    .filter((device) => device.accountId === account.accountId)
    .slice(-5)
    .reverse();
  const allConnectedDevices = Object.values(state.devices).filter(
    (device) => device.accountId === account.accountId
  );
  const integrationSummary = buildIntegrationSummary(account.integrations);

  const { interactionState: _interactionState, integrations: _integrations, ...accountData } = account;
  void _interactionState;
  void _integrations;

  return {
    ...accountData,
    integrations: integrationSummary.items,
    usageSnapshot,
    plan,
    processedWebhookEventCount: account.subscription.processedWebhookEventRefs.length,
    deviceSummary,
    integrationSummary: {
      total: integrationSummary.total,
      connected: integrationSummary.connected,
      needsAttention: integrationSummary.needsAttention,
    },
    interactionSummary: {
      threadCount: interactionState.threads.length,
      messageCount: interactionState.messages.length,
      memoryItemCount: interactionState.memoryItems.length,
      learningDraftCount: interactionState.learningDrafts.length,
    },
    recentLedgerEntries: state.ledger
      .filter((entry) => entry.accountId === account.accountId)
      .slice(-10)
      .reverse(),
    recentEvaluationSignals,
    evaluationSignalCount: accountEvaluationSignals.length,
    recentNotifications,
    recentDevices: connectedDevices,
    recentLearningDrafts: interactionState.learningDrafts.slice(-5).reverse(),
    learningEventCount: accountLearningEvents.length,
    policySnapshot: buildAccountPolicySnapshot(account, plan),
    connectionRegistry: buildHostedConnectionRegistry({
      account,
      devices: allConnectedDevices,
    }),
  };
}

function buildHostedAccountView(accountView: ReturnType<typeof buildAccountView>) {
  const {
    interactionSummary: _interactionSummary,
    recentLedgerEntries: _recentLedgerEntries,
    recentEvaluationSignals: _recentEvaluationSignals,
    evaluationSignalCount: _evaluationSignalCount,
    recentNotifications: _recentNotifications,
    recentDevices: _recentDevices,
    recentLearningDrafts: _recentLearningDrafts,
    learningEventCount: _learningEventCount,
    policySnapshot: _policySnapshot,
    connectionRegistry: _connectionRegistry,
    ...hostedAccount
  } = accountView;
  void _interactionSummary;
  void _recentLedgerEntries;
  void _recentEvaluationSignals;
  void _evaluationSignalCount;
  void _recentNotifications;
  void _recentDevices;
  void _recentLearningDrafts;
  void _learningEventCount;
  void _policySnapshot;
  void _connectionRegistry;

  return hostedAccount;
}

function buildHostedProfile(state: ControlPlaneState, account: ControlPlaneAccount) {
  const accountUser = account.ownerUserId ? state.users[account.ownerUserId] : undefined;
  const accountView = buildHostedAccountView(buildAccountView(state, account));
  const deviceSummary = accountView.deviceSummary;
  const session = {
    userId: accountUser?.userId ?? account.ownerUserId ?? '',
    email: accountUser?.email ?? '',
    name: accountUser?.displayName ?? account.displayName,
    accountId: account.accountId,
    ownerType: accountUser?.ownerType ?? account.ownerType,
    role: accountUser?.role ?? 'owner',
    planId: account.subscription.planId,
    accountStatus: account.status,
    subscriptionStatus: account.subscription.status,
    subscriptionSyncState: account.subscription.syncState,
    hostedAccess: account.entitlements.hostedAccess,
    hostedUsageAccounting: account.entitlements.hostedUsageAccounting,
    balanceCredits: account.balanceCredits,
    deviceCount: deviceSummary.total,
    activeDeviceCount: deviceSummary.active,
  };

  return {
    session,
    user: accountUser
      ? {
          userId: accountUser.userId,
          email: accountUser.email,
          displayName: accountUser.displayName,
          ownerType: accountUser.ownerType,
          role: accountUser.role,
          status: accountUser.status,
        }
      : undefined,
    account: accountView,
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

function countSubscriptionStates(state: ControlPlaneState) {
  return Object.values(state.accounts).reduce(
    (summary, account) => {
      summary.total += 1;
      summary[account.subscription.status] += 1;
      summary[account.subscription.syncState] += 1;
      if (account.subscription.status === 'active' || account.subscription.status === 'trialing') {
        summary.ready += 1;
      }
      if (account.subscription.syncState === 'pending') {
        summary.billingPending += 1;
      }
      if (account.subscription.syncState === 'failed') {
        summary.syncFailed += 1;
      }
      return summary;
    },
    {
      total: 0,
      trialing: 0,
      active: 0,
      past_due: 0,
      suspended: 0,
      canceled: 0,
      unbound: 0,
      pending: 0,
      synced: 0,
      failed: 0,
      ready: 0,
      billingPending: 0,
      syncFailed: 0,
    } as {
      total: number;
      trialing: number;
      active: number;
      past_due: number;
      suspended: number;
      canceled: number;
      unbound: number;
      pending: number;
      synced: number;
      failed: number;
      ready: number;
      billingPending: number;
      syncFailed: number;
    }
  );
}

function countDeviceStates(state: ControlPlaneState) {
  return Object.values(state.devices).reduce(
    (summary, device) => {
      summary.total += 1;
      summary[device.status] += 1;
      return summary;
    },
    {
      total: 0,
      pending: 0,
      active: 0,
      revoked: 0,
      expired: 0,
    }
  );
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

function createLearningEvent(
  accountId: string,
  input: LearningEventRecordInput & { eventId?: string; createdAt?: string }
): ControlPlaneLearningEvent {
  const reasoningSteps =
    input.reasoningSteps ??
    [
      `input: ${input.input.slice(0, 240)}`,
      `intent: ${input.intent}`,
      `plan: ${input.plan}`,
      `action: ${input.metadata?.actionSummary ? String(input.metadata.actionSummary) : 'no tool action'}`,
      `observe: ${input.metadata?.observationSummary ? String(input.metadata.observationSummary) : 'request completed'}`,
      `refine: ${input.failureReason ?? 'retain grounded answer'}`,
      `output: ${(input.output ?? '').slice(0, 240)}`,
    ];
  const planStub = {
    stages: ['intent', 'routing', 'retrieval', 'tooling', 'synthesis', 'citation', 'evaluation'],
    searchRounds: 0,
    maxUrls: 0,
    temperature: 0,
    reasoningDepth: 'standard',
    taskIntent: input.intent,
    intentConfidence: 'medium',
    uncertainty: 'medium',
    routingMode: 'local_first',
    expandSearchQueries: false,
    retrieval: {
      rounds: 0,
      maxUrls: 0,
      rerankTopK: 0,
      language: 'en',
      expandSearchQueries: false,
    },
    capabilityPolicy: [],
    evaluation: {
      collectRetrievalSignals: false,
      collectToolSignals: false,
      captureUsageSignals: false,
      promoteLearnings: true,
    },
    usageBudget: {
      inference: 0,
      retrieval: 0,
      integrations: 0,
      evaluation: 0,
    },
    executionMode: 'single',
    teamPolicy: {
      enabledByDefault: false,
      reasons: [],
      maxConcurrentAgents: 0,
      maxTasksPerRun: 0,
      allowCloudEscalation: false,
      modelRoutingMode: 'local_only',
      riskBoundary: 'read_only',
      requiredRoles: [],
    },
    surface: 'shared-vps',
    mode: 'speed',
    executionPolicy: {
      preferredOrder: [],
      primary: {
        kind: 'direct_answer',
        source: 'none',
        reason: 'learning event',
        requiresConfirmation: false,
      },
      candidates: [],
      shouldRetrieve: false,
      shouldDiscoverMcp: false,
      shouldEscalateModel: false,
      requiresConfirmation: false,
      decisionSummary: 'learning event',
      notes: [],
    },
    skillPolicy: {
      selectedSkillId: 'learning_event',
      selectedSkillTitle: 'Learning event',
      selectedSkillVersion: '1',
      resultShape: 'answer',
      policyBoundary: 'workspace',
      preferredCapabilityIds: [],
      requiresConfirmation: false,
      decisionSummary: 'learning event',
      notes: [],
      candidates: [],
      stages: [],
      selectedTechniques: [],
    },
  } as OrchestrationPlan;
  const evaluation = evaluateReasoningOutcome({
    input: input.input,
    intent: input.intent,
    plan: planStub,
    output: input.output ?? '',
    success: input.success,
    failureReason: input.failureReason,
    latencyMs: input.latencyMs,
    citationCount: Number(input.metadata?.citationCount ?? 0),
    toolCallCount: Number(input.metadata?.toolCallCount ?? 0),
  });

  return {
    eventId: input.eventId ?? createId('lgn'),
    accountId,
    requestId: input.requestId,
    source: input.source,
    input: input.input,
    intent: input.intent,
    taskType: resolveLearningTaskType(input),
    spaceId: resolveLearningSpaceId(accountId, input),
    plan: input.plan,
    reasoningSteps,
    reasoningTrace: reasoningSteps,
    output: input.output ?? '',
    betterOutput: input.betterOutput ?? '',
    success: input.success,
    failureReason: input.failureReason,
    feedback: input.feedback ?? {},
    latencyMs: input.latencyMs,
    score: typeof input.score === 'number' ? input.score : evaluation.score,
    accepted: typeof input.accepted === 'boolean' ? input.accepted : (typeof input.score === 'number' ? input.score >= 0.6 : evaluation.score >= 0.6),
    modelId: input.modelId,
    modelProvider: input.modelProvider,
    isSafeForLearning: input.isSafeForLearning ?? false,
    createdAt: input.createdAt ?? new Date().toISOString(),
    updatedAt: input.createdAt ?? new Date().toISOString(),
    metadata: input.metadata ?? {},
  };
}

export class ControlPlaneService {
  private pending = Promise.resolve();

  constructor(
    private readonly store: ControlPlaneStateStore,
    private readonly databaseUrl?: string
  ) {}

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

    return new ControlPlaneService(store, databaseUrl);
  }

  async listPlans() {
    return controlPlanePlanCatalog;
  }

  async health() {
    const state = await this.readState();
    const runtime = buildControlPlaneRuntimeSnapshot(this.store.kind);
    const version = getRuntimeVersionInfo();
    const subscriptionSummary = countSubscriptionStates(state);
    const deviceSummary = countDeviceStates(state);
    const evaluationSummary = buildControlPlaneEvaluationSummary(state.evaluationSignals);
    const counts = {
      accounts: Object.keys(state.accounts).length,
      users: Object.keys(state.users).length,
      devices: Object.keys(state.devices).length,
      deviceLinks: Object.keys(state.deviceLinks).length,
      ledgerEntries: state.ledger.length,
      evaluationSignals: state.evaluationSignals.length,
      learningEvents: state.learningEvents.length,
    };
    const database = await buildControlPlaneDatabaseHealthSnapshot(this.store.kind, getControlPlanePoolStats());
    const truth =
      this.store.kind === 'postgres'
        ? await readCanonicalSharedTruthSnapshot(getControlPlanePool())
        : {
            expected: [],
            present: [],
            missing: [],
          };

    return {
      ok: true,
      service: 'elyan-control-plane',
      version: version.version,
      releaseTag: version.releaseTag,
      buildSha: version.buildSha,
      surface: runtime.surface,
      storage: runtime.storage,
      activeDatabaseMode: runtime.activeDatabaseMode,
      databaseConfigured: runtime.databaseConfigured,
      postgresReachable: database.postgresReachable,
      migrationsApplied: database.migrationsApplied,
      schemaReady: database.schemaReady,
      billingConfigured: runtime.billingConfigured,
      billingMode: runtime.billingMode,
      hostedReady: runtime.hostedReady,
      missingEnvKeys: runtime.missingEnvKeys,
      readiness: runtime.readiness,
      stateVersion: state.version,
      accountCount: counts.accounts,
      userCount: counts.users,
      deviceCount: counts.devices,
      deviceLinkCount: counts.deviceLinks,
      ledgerEntryCount: counts.ledgerEntries,
      learningEventCount: counts.learningEvents,
      counts,
      database,
      truth,
      syncSummary: {
        subscriptions: subscriptionSummary,
        devices: deviceSummary,
      },
      evaluationSummary,
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

    const deviceSummary = countAccountDeviceStates(state, account.accountId);

    return {
      userId: user.userId,
      email: user.email,
      name: user.displayName,
      accountId: account.accountId,
      ownerType: user.ownerType,
      role: user.role,
      planId: account.subscription.planId,
      accountStatus: account.status,
      subscriptionStatus: account.subscription.status,
      subscriptionSyncState: account.subscription.syncState,
      hostedAccess: account.entitlements.hostedAccess,
      hostedUsageAccounting: account.entitlements.hostedUsageAccounting,
      balanceCredits: account.balanceCredits,
      deviceCount: deviceSummary.total,
      activeDeviceCount: deviceSummary.active,
    };
  }

  async getHostedProfile(accountId: string) {
    const state = await this.readState();
    const account = state.accounts[accountId];

    if (!account) {
      throw new ControlPlaneNotFoundError('Account', accountId);
    }

    return buildHostedProfile(state, account);
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
    const bundle = await this.quoteUsageBundle(accountId, [input]);
    const quote = bundle.quotes[0];

    if (!quote) {
      throw new ControlPlaneValidationError('Usage quote requires at least one charge');
    }

    return quote;
  }

  async quoteUsageBundle(accountId: string, inputs: ControlPlaneUsageInput[]) {
    const state = await this.readState();
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
    const requestTokens = inputs.reduce((total, input) => total + Math.max(0, Math.trunc(input.tokens ?? 0)), 0);
    const allowance = evaluateUsageConsumption(
      normalizedSnapshot,
      1,
      inputs.length,
      requestTokens,
      prepared.balanceBefore,
      prepared.balanceAfter
    );
    const denial = describeUsageLimitDenial(allowance, plan);

    const quotes = prepared.charges.map((charge) => {
      const creditsDelta = formatCredits(charge.creditsDelta);

      return {
        accountId,
        planId: account.subscription.planId,
        domain: charge.input.domain,
        units: charge.input.units,
        creditsDelta,
        balanceBefore: formatCredits(prepared.balanceBefore),
        balanceAfter: formatCredits(prepared.allowed ? prepared.balanceAfter : prepared.balanceBefore),
        allowed: prepared.allowed && allowance.allowed,
        denialReason: allowance.denialReason ?? (prepared.allowed ? undefined : 'monthly_credits_exhausted'),
        resetAt: allowance.resetAt,
        remainingRequests: allowance.remainingRequests,
        remainingHostedToolActionCalls: allowance.remainingHostedToolActionCalls,
        remainingTokens: allowance.remainingTokens,
        monthlyCreditsRemaining: allowance.monthlyCreditsRemaining,
        requestTokens,
      } satisfies ControlPlaneUsageQuote;
    });

    return {
      account: buildAccountView(state, account),
      quotes,
      allowed: prepared.allowed && allowance.allowed,
      denialReason: denial?.code ?? allowance.denialReason,
      resetAt: allowance.resetAt,
      remainingRequests: allowance.remainingRequests,
      remainingHostedToolActionCalls: allowance.remainingHostedToolActionCalls,
      remainingTokens: allowance.remainingTokens,
      monthlyCreditsRemaining: allowance.monthlyCreditsRemaining,
      requestTokens,
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
      const requestTokens = inputs.reduce((total, input) => total + Math.max(0, Math.trunc(input.tokens ?? 0)), 0);
      const now = new Date().toISOString();
      const allowance = evaluateUsageConsumption(
        normalizedSnapshot,
        1,
        inputs.length,
        requestTokens,
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
                : allowance.denialReason === 'daily_tokens_limit'
                  ? 'daily_tokens_limit'
                : 'daily_requests_limit',
            resetAt: allowance.resetAt,
            remainingRequests: allowance.remainingRequests,
            remainingHostedToolActionCalls: allowance.remainingHostedToolActionCalls,
            remainingTokens: allowance.remainingTokens,
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
        usageSnapshot: advanceUsageSnapshot(normalizedSnapshot, plan, nextBalance, 1, inputs.length, requestTokens, new Date(now)),
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
          requestTokens,
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

  async recordLearningEvent(accountId: string, input: LearningEventRecordInput) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];

      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      this.assertHostedImprovementAllowed(account);

      const existing = state.learningEvents.find(
        (event) => event.accountId === accountId && event.requestId === input.requestId
      );

      if (existing) {
        return existing;
      }

      const event = createLearningEvent(accountId, input);
      state.learningEvents.push(event);
      await this.store.write(state);

      const signal = deriveLearningSignal({
        accountId,
        spaceId: event.spaceId,
        eventId: event.eventId,
        requestId: event.requestId,
        source: event.source,
        input: event.input,
        output: event.output,
        intent: event.intent,
        taskType: event.taskType,
        success: event.success,
        failureReason: event.failureReason,
        feedback: event.feedback,
        latencyMs: event.latencyMs,
        score: event.score,
        accepted: event.accepted,
        modelId: event.modelId,
        modelProvider: event.modelProvider,
        isSafeForLearning: event.isSafeForLearning,
        metadata: {
          ...event.metadata,
          queryLength: event.metadata.queryLength,
          source_count: event.metadata.sourceCount,
          citation_count: event.metadata.citationCount,
          reasoningDepth: event.metadata.reasoningDepth,
          routingMode: event.metadata.routingMode,
          teacherStrategy: event.metadata.teacherStrategy,
          evaluatorNotes: event.metadata.evaluatorNotes,
          discardReason: event.metadata.discardReason,
        },
        createdAt: event.createdAt,
      });

      if (signal.isSafeForLearning) {
        const artifacts = buildLearningArtifacts(signal);
        const persistResults = await Promise.allSettled([
          persistLearningArtifacts(this.databaseUrl, artifacts),
          ingestRetrievalText({
            accountId,
            spaceId: event.spaceId,
            sourceKind: 'learning',
            sourceName: 'learning_signal',
            title: `${signal.taskType} learning signal`,
            content: buildLearningRetrievalText(signal, artifacts),
            metadata: {
              request_id: event.requestId,
              event_id: event.eventId,
              space_id: event.spaceId,
              task_type: signal.taskType,
              success_score: signal.successScore,
              prompt_effectiveness: signal.promptEffectiveness,
              model_performance: signal.modelPerformance,
              latency_ms: signal.latencyMs,
              model_id: event.modelId,
              model_provider: event.modelProvider,
              source: event.source,
              is_safe_for_learning: signal.isSafeForLearning,
            },
          }),
        ]);

        for (const result of persistResults) {
          if (result.status === 'rejected') {
            console.warn('Failed to persist hosted learning output', result.reason);
          }
        }
      }

      return event;
    });
  }

  async getInteractionContext(accountId: string, input: InteractionContextInput) {
    const state = await this.readState();
    const account = state.accounts[accountId];

    if (!account) {
      throw new ControlPlaneNotFoundError('Account', accountId);
    }

    const interactionState = normalizeInteractionState(account.interactionState);
    const threadId = input.threadId ?? (input.conversationId ? `${input.source}:${input.conversationId}` : undefined);
    const normalizedQuery = input.query.toLowerCase();
    const matchingThreads = interactionState.threads
      .filter((thread) => thread.status === 'active')
      .filter((thread) => {
        if (threadId && thread.threadId === threadId) {
          return true;
        }

        const haystack = `${thread.title} ${thread.summary} ${thread.source}`.toLowerCase();
        return normalizedQuery.split(/\s+/).filter(Boolean).some((token) => token.length >= 3 && haystack.includes(token));
      })
      .slice(-3)
      .reverse();
    const pinnedMemory = interactionState.memoryItems
      .filter((item) => item.pinned || item.promoted)
      .filter((item) => {
        const haystack = `${item.title} ${item.summary}`.toLowerCase();
        return normalizedQuery.split(/\s+/).filter(Boolean).some((token) => token.length >= 3 && haystack.includes(token));
      })
      .slice(-6)
      .reverse();
    const recentMemory = interactionState.memoryItems
      .filter((item) => !item.pinned && !item.promoted)
      .slice(-4)
      .reverse();
    const semanticDocuments = await searchRetrievalDocumentsHybrid(input.query, {
      accountId,
      sourceKinds: ['bootstrap', 'web', 'learning'],
      limit: 4,
    });
    const memory = buildMemoryContext({
      thread: threadId
        ? interactionState.threads.find((thread) => thread.threadId === threadId)
        : matchingThreads[0],
      messages: interactionState.messages,
      memoryItems: [...pinnedMemory, ...recentMemory],
      learningDrafts: interactionState.learningDrafts,
      semanticDocuments,
    });

    const contextBlocks = filterContextBlocks(
      [
        matchingThreads.length > 0
          ? `Relevant threads:\n${matchingThreads
              .map((thread) => `- ${thread.title} [${thread.intent}] ${thread.summary}`)
              .join('\n')}`
          : '',
        ...memory.contextBlocks,
      ],
      { maxTokens: 1_800, maxBlocks: 8, minScore: 0.15 }
    );

    return {
      threadId,
      contextBlocks,
      thread: threadId
        ? interactionState.threads.find((thread) => thread.threadId === threadId)
        : matchingThreads[0],
      memoryItems: [...pinnedMemory, ...recentMemory],
    };
  }

  async recordInteraction(accountId: string, input: InteractionRecordInput) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];

      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      const interactionState = normalizeInteractionState(account.interactionState);
      const threadId = input.conversationId ? `${input.source}:${input.conversationId}` : undefined;
      const threadTitle = input.threadTitle ?? buildInteractionThreadTitle(input.query);
      const threadSummary = summarizeInteractionThread(input.query, input.responseText);

      let thread = interactionState.threads.find((entry) => entry.threadId === threadId);
      if (!thread) {
        thread = createInteractionThread(
          accountId,
          input.source,
          input.intent,
          threadTitle,
          threadSummary,
          {
            conversationId: input.conversationId,
            modelId: input.modelId,
            userId: input.userId,
            displayName: input.displayName,
            confidence: input.confidence,
          },
          threadId
        );
        interactionState.threads.push(thread);
      }

      const userMessage = createInteractionMessage(
        thread.threadId,
        accountId,
        'user',
        input.query,
        input.source,
        {
          conversationId: input.conversationId,
          messageId: input.messageId,
          modelId: input.modelId,
          userId: input.userId,
          displayName: input.displayName,
          ...input.metadata,
        }
      );
      const assistantMessage = createInteractionMessage(
        thread.threadId,
        accountId,
        'assistant',
        input.responseText,
        'answer_engine',
        {
          modelId: input.modelId,
          mode: input.mode,
          sources: input.sources ?? [],
          citationCount: input.citationCount ?? 0,
        }
      );

      interactionState.messages.push(userMessage, assistantMessage);
      thread.messageCount += 2;
      thread.summary = threadSummary;
      thread.intent = input.intent;
      thread.updatedAt = new Date().toISOString();
      thread.lastMessageAt = assistantMessage.createdAt;
      thread.metadata = {
        ...thread.metadata,
        modelId: input.modelId,
        confidence: input.confidence,
      };

      const memoryKind = deriveMemoryKind(input.intent, input.query);
      const memoryTitle = `${threadTitle}${memoryKind === 'recent' ? '' : ` (${memoryKind})`}`;
      const memorySummary = buildMemorySummary(
        input.responseText.length > 0 ? input.responseText : input.query,
        220
      );
      const memoryItem = createInteractionMemoryItem(accountId, memoryKind, memoryTitle, memorySummary, 'user', {
        threadId: thread.threadId,
        confidence: input.confidence === 'high' ? 0.9 : input.confidence === 'medium' ? 0.7 : 0.5,
        promoted: memoryKind !== 'recent' && input.intent !== 'direct_answer',
        metadata: {
          modelId: input.modelId,
          mode: input.mode,
          citationCount: input.citationCount ?? 0,
          sources: input.sources ?? [],
        },
      });

      interactionState.memoryItems.push(memoryItem);

      let learningDraft: ControlPlaneLearningDraft | undefined;
      if (input.intent === 'research' || (input.citationCount ?? 0) > 0) {
        learningDraft = createLearningDraft(
          accountId,
          input.intent === 'research' ? 'research' : memoryKind === 'preference' ? 'preference' : 'project',
          threadTitle,
          threadSummary,
          input.responseText,
          input.source,
          {
            threadId: thread.threadId,
            metadata: {
              modelId: input.modelId,
              mode: input.mode,
              citationCount: input.citationCount ?? 0,
              sources: input.sources ?? [],
            },
          }
        );
        interactionState.learningDrafts.push(learningDraft);
      }

      account.interactionState = {
        threads: trimInteractionHistory(interactionState.threads, 40),
        messages: trimInteractionHistory(interactionState.messages, 160),
        memoryItems: trimInteractionHistory(interactionState.memoryItems, 80),
        learningDrafts: trimInteractionHistory(interactionState.learningDrafts, 40),
      };
      account.updatedAt = new Date().toISOString();
      state.accounts[accountId] = account;
      await this.store.write(state);

      return {
        thread,
        memoryItem,
        learningDraft,
        messages: [userMessage, assistantMessage],
      };
    });
  }

  async promoteLearningDraft(accountId: string, draftId: string) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];
      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      const interactionState = normalizeInteractionState(account.interactionState);
      const draft = interactionState.learningDrafts.find((entry) => entry.draftId === draftId);

      if (!draft) {
        throw new ControlPlaneNotFoundError('Learning draft', draftId);
      }

      draft.status = 'promoted';
      draft.updatedAt = new Date().toISOString();

      const memoryItem = createInteractionMemoryItem(
        accountId,
        draft.kind === 'research' ? 'project' : draft.kind,
        draft.title,
        draft.summary,
        'learning',
        {
          threadId: draft.threadId,
          promoted: true,
          promotedFromDraftId: draft.draftId,
          confidence: 0.95,
          metadata: draft.metadata,
        }
      );

      interactionState.memoryItems.push(memoryItem);
      account.interactionState = {
        threads: trimInteractionHistory(interactionState.threads, 40),
        messages: trimInteractionHistory(interactionState.messages, 160),
        memoryItems: trimInteractionHistory(interactionState.memoryItems, 80),
        learningDrafts: trimInteractionHistory(interactionState.learningDrafts, 40),
      };
      account.updatedAt = new Date().toISOString();
      state.accounts[accountId] = account;
      await this.store.write(state);

      return {
        draft,
        memoryItem,
      };
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
      .reverse()
      .map((device) => buildHostedDevice(device));
  }

  async listIntegrations(accountId: string) {
    const state = await this.readState();
    const account = state.accounts[accountId];

    if (!account) {
      throw new ControlPlaneNotFoundError('Account', accountId);
    }

    return Object.values(account.integrations)
      .map((integration) => sanitizeIntegration(integration))
      .sort((left, right) => right.updatedAt.localeCompare(left.updatedAt));
  }

  async beginIntegrationConnection(
    accountId: string,
    userId: string,
    input: ControlPlaneIntegrationConnectStartInput & { authorizationUrl: string; state: string }
  ) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];
      const user = state.users[userId];
      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      if (!user || user.accountId !== accountId) {
        throw new ControlPlaneAuthenticationError('Integration linking requires the signed-in account owner');
      }

      const config = getIntegrationProviderConfig(input.provider);
      if (!isIntegrationProviderConfigured(input.provider)) {
        throw new ControlPlaneConfigurationError(`${config.displayName} OAuth is not configured`);
      }

      const now = new Date().toISOString();
      const existing = Object.values(account.integrations).find((integration) => integration.provider === input.provider);
      const integrationId = existing?.integrationId ?? createId('int');
      const nextIntegration: ControlPlaneIntegration = {
        integrationId,
        accountId,
        provider: input.provider,
        displayName: config.displayName,
        status: 'connecting',
        scopes: existing?.scopes?.length ? existing.scopes : config.defaultScopes,
        surfaces: config.surfaces,
        externalAccountId: existing?.externalAccountId,
        externalAccountLabel: existing?.externalAccountLabel,
        accessTokenCiphertext: existing?.accessTokenCiphertext,
        refreshTokenCiphertext: existing?.refreshTokenCiphertext,
        idTokenCiphertext: existing?.idTokenCiphertext,
        expiresAt: existing?.expiresAt,
        lastSyncedAt: existing?.lastSyncedAt,
        lastError: undefined,
        metadata: {
          ...(existing?.metadata ?? {}),
          pendingState: input.state,
          returnTo: input.returnTo ?? (existing?.metadata?.returnTo as string | undefined),
          authorizationUrl: input.authorizationUrl,
          requestedByUserId: userId,
        },
        createdAt: existing?.createdAt ?? now,
        updatedAt: now,
      };

      state.accounts[accountId] = {
        ...account,
        integrations: {
          ...account.integrations,
          [integrationId]: nextIntegration,
        },
        updatedAt: now,
      };

      await this.store.write(state);
      return sanitizeIntegration(nextIntegration);
    });
  }

  async completeIntegrationConnection(
    input: ControlPlaneIntegrationCallbackInput & {
      accountId: string;
      userId: string;
      provider: ControlPlaneIntegrationProvider;
      codeVerifier: string;
      returnTo?: string;
    }
  ) {
    return this.withState(async (state) => {
      const account = state.accounts[input.accountId];
      const user = state.users[input.userId];

      if (!account) {
        throw new ControlPlaneNotFoundError('Account', input.accountId);
      }

      if (!user || user.accountId !== input.accountId) {
        throw new ControlPlaneAuthenticationError('Integration linking requires the signed-in account owner');
      }

      const config = getIntegrationProviderConfig(input.provider);
      const existing = Object.values(account.integrations).find((integration) => integration.provider === input.provider);
      const now = new Date().toISOString();
      if (existing?.metadata?.pendingState && existing.metadata.pendingState !== input.state) {
        throw new ControlPlaneValidationError('Integration callback state mismatch');
      }
      const tokenResponse = await exchangeOAuthCode(input.provider, {
        code: input.code,
        redirectUri: buildIntegrationRedirectUri(input.provider),
        codeVerifier: input.codeVerifier,
      });
      const profile = await fetchIntegrationProfile(input.provider, tokenResponse.access_token);
      const scopes = tokenResponse.scope?.split(/\s+/).filter(Boolean);
      const integrationId = existing?.integrationId ?? createId('int');
      const nextIntegration: ControlPlaneIntegration = {
        integrationId,
        accountId: input.accountId,
        provider: input.provider,
        displayName: config.displayName,
        status: 'connected',
        scopes: scopes?.length ? scopes : existing?.scopes?.length ? existing.scopes : config.defaultScopes,
        surfaces: config.surfaces,
        externalAccountId: profile.externalAccountId,
        externalAccountLabel: profile.externalAccountLabel,
        accessTokenCiphertext: encryptIntegrationSecret(tokenResponse.access_token),
        refreshTokenCiphertext: tokenResponse.refresh_token
          ? encryptIntegrationSecret(tokenResponse.refresh_token)
          : existing?.refreshTokenCiphertext,
        idTokenCiphertext: tokenResponse.id_token
          ? encryptIntegrationSecret(tokenResponse.id_token)
          : existing?.idTokenCiphertext,
        expiresAt:
          tokenResponse.expires_in && Number.isFinite(tokenResponse.expires_in)
            ? new Date(Date.now() + tokenResponse.expires_in * 1000).toISOString()
            : existing?.expiresAt,
        lastSyncedAt: now,
        lastError: undefined,
        metadata: {
          ...(existing?.metadata ?? {}),
          ...profile.metadata,
          connectedAt: now,
          pendingState: undefined,
          returnTo: input.returnTo ?? (existing?.metadata?.returnTo as string | undefined),
        },
        createdAt: existing?.createdAt ?? now,
        updatedAt: now,
      };

      state.accounts[input.accountId] = {
        ...account,
        integrations: {
          ...account.integrations,
          [integrationId]: nextIntegration,
        },
        updatedAt: now,
      };

      await this.store.write(state);

      return {
        integration: sanitizeIntegration(nextIntegration),
        account: buildAccountView(state, state.accounts[input.accountId]),
      };
    });
  }

  async disconnectIntegration(accountId: string, input: ControlPlaneIntegrationDisconnectInput) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];
      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      const integration = account.integrations[input.integrationId];
      if (!integration) {
        throw new ControlPlaneNotFoundError('Integration', input.integrationId);
      }

      const now = new Date().toISOString();
      const nextIntegration: ControlPlaneIntegration = {
        ...integration,
        status: 'revoked',
        accessTokenCiphertext: undefined,
        refreshTokenCiphertext: undefined,
        idTokenCiphertext: undefined,
        lastError: 'Disconnected by user',
        updatedAt: now,
        metadata: {
          ...(integration.metadata ?? {}),
          disconnectedAt: now,
        },
      };

      state.accounts[accountId] = {
        ...account,
        integrations: {
          ...account.integrations,
          [integration.integrationId]: nextIntegration,
        },
        updatedAt: now,
      };

      await this.store.write(state);
      return sanitizeIntegration(nextIntegration);
    });
  }

  async executeIntegrationAction(accountId: string, input: ControlPlaneIntegrationActionInput) {
    const context = await this.resolveIntegrationAccessContext(accountId, input.provider, input.integrationId);
    await this.recordUsage(accountId, {
      domain: 'integrations',
      units: 1,
      source: 'hosted_api',
      note: `${input.provider}:${input.action}`,
    });
    const provider = input.provider;
    const action = input.action;
    const parameters = input.parameters ?? {};
    const now = new Date().toISOString();

    try {
      let result: Record<string, unknown>;

      if (provider === 'google') {
        result = await this.executeGoogleIntegrationAction(context.accessToken, action, parameters);
      } else if (provider === 'github') {
        result = await this.executeGitHubIntegrationAction(context.accessToken, action, parameters);
      } else {
        result = await this.executeNotionIntegrationAction(context.accessToken, action, parameters);
      }

      const integration = await this.touchIntegration(accountId, context.integration.integrationId, {
        lastSyncedAt: now,
        lastError: null,
        status: 'connected',
      });

      return {
        ok: true,
        integration,
        result,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : 'integration action failed';
      await this.touchIntegration(accountId, context.integration.integrationId, {
        lastError: message,
        status:
          message.includes('unauthorized') || message.includes('401')
            ? 'expired'
            : context.integration.status,
      });
      throw error;
    }
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
      const existing = Object.values(state.deviceLinks).find(
        (link) =>
          link.accountId === accountId &&
          link.userId === userId &&
          link.deviceLabel === input.deviceLabel &&
          (link.status === 'pending' || link.status === 'complete') &&
          Date.parse(link.expiresAt) > Date.parse(now)
      );

      if (existing) {
        return existing;
      }

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

      if (Date.parse(link.expiresAt) <= Date.parse(now)) {
        link.status = 'expired';
        await this.store.write(state);
        throw new ControlPlaneConflictError('Device link has expired');
      }

      if (link.status === 'complete' || link.status === 'consumed') {
        const device = Object.values(state.devices).find(
          (entry) =>
            entry.accountId === link.accountId &&
            entry.userId === link.userId &&
            entry.deviceLabel === link.deviceLabel &&
            entry.deviceToken === link.deviceToken
        );

        if (device) {
          return {
            link,
            device,
          };
        }

        throw new ControlPlaneConflictError(`Device link is ${link.status}`);
      }

      if (link.status !== 'pending') {
        throw new ControlPlaneConflictError(`Device link is ${link.status}`);
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

  async rotateDeviceToken(deviceToken: string) {
    return this.withState(async (state) => {
      const device = this.findDeviceByToken(state, deviceToken);

      if (!device) {
        throw new ControlPlaneNotFoundError('Device', deviceToken);
      }

      if (device.status !== 'active') {
        throw new ControlPlaneEntitlementError(`Device is ${device.status}`);
      }

      const now = new Date().toISOString();
      const nextDeviceToken = `devtok_${randomUUID().replace(/-/g, '')}`;
      const nextDevice: ControlPlaneDevice = {
        ...device,
        deviceToken: nextDeviceToken,
        metadata: {
          ...device.metadata,
          rotationStatus: 'rotated',
          rotatedAt: now,
          previousTokenFingerprint: device.deviceToken.slice(-8),
        },
        updatedAt: now,
        lastSeenAt: now,
      };

      state.devices[device.deviceId] = nextDevice;

      for (const link of Object.values(state.deviceLinks)) {
        if (link.deviceToken === deviceToken) {
          link.status = 'consumed';
          link.consumedAt = link.consumedAt ?? now;
          link.deviceToken = nextDeviceToken;
        }
      }

      await this.store.write(state);

      return {
        ok: true,
        device: nextDevice,
        previousDeviceToken: deviceToken,
        rotatedAt: now,
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

  private findIntegration(
    account: ControlPlaneAccount,
    provider: ControlPlaneIntegrationProvider,
    integrationId?: string
  ) {
    if (integrationId) {
      const byId = account.integrations[integrationId];
      if (!byId) {
        throw new ControlPlaneNotFoundError('Integration', integrationId);
      }

      if (byId.provider !== provider) {
        throw new ControlPlaneValidationError('Integration provider mismatch');
      }

      return byId;
    }

    const byProvider = Object.values(account.integrations).find((integration) => integration.provider === provider);
    if (!byProvider) {
      throw new ControlPlaneNotFoundError('Integration', provider);
    }

    return byProvider;
  }

  private async mutateIntegration(
    accountId: string,
    integrationId: string,
    updater: (integration: ControlPlaneIntegration, account: ControlPlaneAccount) => ControlPlaneIntegration
  ) {
    return this.withState(async (state) => {
      const account = state.accounts[accountId];
      if (!account) {
        throw new ControlPlaneNotFoundError('Account', accountId);
      }

      const integration = account.integrations[integrationId];
      if (!integration) {
        throw new ControlPlaneNotFoundError('Integration', integrationId);
      }

      const nextIntegration = updater(integration, account);
      state.accounts[accountId] = {
        ...account,
        integrations: {
          ...account.integrations,
          [integrationId]: nextIntegration,
        },
        updatedAt: nextIntegration.updatedAt ?? new Date().toISOString(),
      };

      await this.store.write(state);
      return sanitizeIntegration(nextIntegration);
    });
  }

  private async refreshIntegrationAccessToken(
    accountId: string,
    integration: ControlPlaneIntegration
  ) {
    if (!integration.refreshTokenCiphertext) {
      throw new ControlPlaneProviderError(
        `${getIntegrationProviderConfig(integration.provider).displayName} connection expired and must be reauthorized`
      );
    }

    const refreshToken = decryptIntegrationSecret(integration.refreshTokenCiphertext);
    const refreshed = await refreshOAuthToken(integration.provider, {
      refreshToken,
      redirectUri: buildIntegrationRedirectUri(integration.provider),
    });
    const now = new Date().toISOString();

    await this.mutateIntegration(accountId, integration.integrationId, (current) => ({
      ...current,
      status: 'connected',
      accessTokenCiphertext: encryptIntegrationSecret(refreshed.access_token),
      refreshTokenCiphertext: refreshed.refresh_token
        ? encryptIntegrationSecret(refreshed.refresh_token)
        : current.refreshTokenCiphertext,
      idTokenCiphertext: refreshed.id_token
        ? encryptIntegrationSecret(refreshed.id_token)
        : current.idTokenCiphertext,
      expiresAt:
        refreshed.expires_in && Number.isFinite(refreshed.expires_in)
          ? new Date(Date.now() + refreshed.expires_in * 1000).toISOString()
          : current.expiresAt,
      lastSyncedAt: now,
      lastError: undefined,
      updatedAt: now,
        metadata: {
        ...current.metadata,
        refreshedAt: now,
      },
    }));

    const state = await this.readState();
    const account = state.accounts[accountId];
    if (!account) {
      throw new ControlPlaneNotFoundError('Account', accountId);
    }

    const refreshedIntegration = account.integrations[integration.integrationId];
    if (!refreshedIntegration) {
      throw new ControlPlaneNotFoundError('Integration', integration.integrationId);
    }

    return refreshedIntegration;
  }

  private async resolveIntegrationAccessContext(
    accountId: string,
    provider: ControlPlaneIntegrationProvider,
    integrationId?: string
  ) {
    const state = await this.readState();
    const account = state.accounts[accountId];

    if (!account) {
      throw new ControlPlaneNotFoundError('Account', accountId);
    }

    let integration = this.findIntegration(account, provider, integrationId);
    if (integration.status === 'revoked' || integration.status === 'disconnected') {
      throw new ControlPlaneProviderError(
        `${getIntegrationProviderConfig(provider).displayName} connection is not active`
      );
    }

    const expiresAtMs = integration.expiresAt ? Date.parse(integration.expiresAt) : Number.NaN;
    const isExpired = Number.isFinite(expiresAtMs) && expiresAtMs <= Date.now() + 60_000;

    if (isExpired) {
      integration = integration.refreshTokenCiphertext
        ? await this.refreshIntegrationAccessToken(accountId, integration)
        : (() => {
            throw new ControlPlaneProviderError(
              `${getIntegrationProviderConfig(provider).displayName} connection expired and must be reauthorized`
            );
          })();
    }

    if (!integration.accessTokenCiphertext) {
      throw new ControlPlaneProviderError(
        `${getIntegrationProviderConfig(provider).displayName} connection has no usable access token`
      );
    }

    return {
      integration,
      publicIntegration: sanitizeIntegration(integration),
      accessToken: decryptIntegrationSecret(integration.accessTokenCiphertext),
    };
  }

  private async requestIntegrationJson(
    provider: ControlPlaneIntegrationProvider,
    url: string,
    init: RequestInit
  ) {
    const response = await fetch(url, init);
    if (response.status === 401) {
      throw new ControlPlaneProviderError(`${getIntegrationProviderConfig(provider).displayName} request unauthorized`);
    }

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new ControlPlaneProviderError(
        `${getIntegrationProviderConfig(provider).displayName} request failed: ${text || response.status}`
      );
    }

    return response.json().catch(() => ({}));
  }

  private async touchIntegration(
    accountId: string,
    integrationId: string,
    patch: Partial<Pick<ControlPlaneIntegration, 'status' | 'lastSyncedAt' | 'updatedAt'>> & {
      lastError?: string | null;
      metadataPatch?: Record<string, unknown>;
    }
  ) {
    return this.mutateIntegration(accountId, integrationId, (current) => ({
      ...current,
      status: patch.status ?? current.status,
      lastSyncedAt: patch.lastSyncedAt ?? current.lastSyncedAt,
      lastError:
        patch.lastError === undefined
          ? current.lastError
          : patch.lastError ?? undefined,
      updatedAt: patch.updatedAt ?? new Date().toISOString(),
      metadata: {
        ...(current.metadata ?? {}),
        ...(patch.metadataPatch ?? {}),
      },
    }));
  }

  private async executeGoogleIntegrationAction(
    accessToken: string,
    action: string,
    parameters: Record<string, unknown>
  ) {
    if (action === 'gmail.listMessages') {
      const input = z
        .object({
          maxResults: z.number().int().positive().max(25).optional(),
          query: z.string().trim().min(1).optional(),
          labelIds: z.array(z.string().min(1)).optional(),
        })
        .parse(parameters);

      const url = new URL('https://gmail.googleapis.com/gmail/v1/users/me/messages');
      url.searchParams.set('maxResults', String(input.maxResults ?? 10));
      if (input.query) {
        url.searchParams.set('q', input.query);
      }
      if (input.labelIds?.length) {
        url.searchParams.set('labelIds', input.labelIds.join(','));
      }

      const payload = await this.requestIntegrationJson('google', url.toString(), {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/json',
        },
      });

      return {
        kind: 'gmail.listMessages',
        messages: Array.isArray((payload as { messages?: unknown }).messages)
          ? (payload as { messages?: Array<Record<string, unknown>> }).messages
          : [],
      };
    }

    if (action === 'gmail.sendMessage') {
      const input = z
        .object({
          to: z.string().trim().email(),
          subject: z.string().trim().min(1),
          text: z.string().min(1),
          cc: z.string().trim().email().optional(),
          bcc: z.string().trim().email().optional(),
        })
        .parse(parameters);

      const lines = [
        `To: ${input.to}`,
        input.cc ? `Cc: ${input.cc}` : null,
        input.bcc ? `Bcc: ${input.bcc}` : null,
        `Subject: ${input.subject}`,
        'Content-Type: text/plain; charset="UTF-8"',
        '',
        input.text,
      ].filter((line): line is string => line !== null);

      const raw = Buffer.from(lines.join('\r\n')).toString('base64url');
      const payload = await this.requestIntegrationJson('google', 'https://gmail.googleapis.com/gmail/v1/users/me/messages/send', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ raw }),
      });

      return {
        kind: 'gmail.sendMessage',
        messageId: (payload as { id?: string }).id ?? null,
      };
    }

    if (action === 'calendar.listEvents') {
      const input = z
        .object({
          calendarId: z.string().trim().min(1).default('primary'),
          timeMin: z.string().trim().datetime().optional(),
          timeMax: z.string().trim().datetime().optional(),
          maxResults: z.number().int().positive().max(50).optional(),
        })
        .parse(parameters);

      const url = new URL(`https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(input.calendarId)}/events`);
      if (input.timeMin) url.searchParams.set('timeMin', input.timeMin);
      if (input.timeMax) url.searchParams.set('timeMax', input.timeMax);
      url.searchParams.set('singleEvents', 'true');
      url.searchParams.set('orderBy', 'startTime');
      url.searchParams.set('maxResults', String(input.maxResults ?? 10));

      const payload = await this.requestIntegrationJson('google', url.toString(), {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/json',
        },
      });

      return {
        kind: 'calendar.listEvents',
        events: Array.isArray((payload as { items?: unknown }).items)
          ? (payload as { items?: Array<Record<string, unknown>> }).items
          : [],
      };
    }

    if (action === 'calendar.createEvent') {
      const input = z
        .object({
          calendarId: z.string().trim().min(1).default('primary'),
          summary: z.string().trim().min(1),
          description: z.string().trim().optional(),
          location: z.string().trim().optional(),
          start: z.string().trim().datetime(),
          end: z.string().trim().datetime(),
        })
        .parse(parameters);

      const payload = await this.requestIntegrationJson(
        'google',
        `https://www.googleapis.com/calendar/v3/calendars/${encodeURIComponent(input.calendarId)}/events`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${accessToken}`,
            Accept: 'application/json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            summary: input.summary,
            description: input.description,
            location: input.location,
            start: { dateTime: input.start },
            end: { dateTime: input.end },
          }),
        }
      );

      return {
        kind: 'calendar.createEvent',
        eventId: (payload as { id?: string }).id ?? null,
      };
    }

    throw new ControlPlaneValidationError(`Unsupported Google integration action: ${action}`);
  }

  private async executeGitHubIntegrationAction(
    accessToken: string,
    action: string,
    parameters: Record<string, unknown>
  ) {
    if (action === 'user.profile') {
      const payload = await this.requestIntegrationJson('github', 'https://api.github.com/user', {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
      });

      return {
        kind: 'user.profile',
        user: payload,
      };
    }

    if (action === 'repos.list') {
      const input = z
        .object({
          perPage: z.number().int().positive().max(100).optional(),
        })
        .parse(parameters);

      const url = new URL('https://api.github.com/user/repos');
      url.searchParams.set('per_page', String(input.perPage ?? 10));
      url.searchParams.set('sort', 'updated');

      const payload = await this.requestIntegrationJson('github', url.toString(), {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
      });

      return {
        kind: 'repos.list',
        repositories: Array.isArray(payload) ? payload : [],
      };
    }

    if (action === 'issues.list') {
      const input = z
        .object({
          owner: z.string().trim().min(1),
          repo: z.string().trim().min(1),
          state: z.enum(['open', 'closed', 'all']).default('open'),
          perPage: z.number().int().positive().max(100).optional(),
        })
        .parse(parameters);

      const url = new URL(`https://api.github.com/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/issues`);
      url.searchParams.set('state', input.state);
      url.searchParams.set('per_page', String(input.perPage ?? 10));

      const payload = await this.requestIntegrationJson('github', url.toString(), {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
        },
      });

      return {
        kind: 'issues.list',
        issues: Array.isArray(payload) ? payload : [],
      };
    }

    if (action === 'issues.comment') {
      const input = z
        .object({
          owner: z.string().trim().min(1),
          repo: z.string().trim().min(1),
          issueNumber: z.number().int().positive(),
          body: z.string().trim().min(1),
        })
        .parse(parameters);

      const payload = await this.requestIntegrationJson(
        'github',
        `https://api.github.com/repos/${encodeURIComponent(input.owner)}/${encodeURIComponent(input.repo)}/issues/${input.issueNumber}/comments`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${accessToken}`,
            Accept: 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ body: input.body }),
        }
      );

      return {
        kind: 'issues.comment',
        commentId: (payload as { id?: string | number }).id ?? null,
      };
    }

    throw new ControlPlaneValidationError(`Unsupported GitHub integration action: ${action}`);
  }

  private async executeNotionIntegrationAction(
    accessToken: string,
    action: string,
    parameters: Record<string, unknown>
  ) {
    if (action === 'search') {
      const input = z
        .object({
          query: z.string().trim().min(1),
          pageSize: z.number().int().positive().max(100).optional(),
        })
        .parse(parameters);

      const payload = await this.requestIntegrationJson('notion', 'https://api.notion.com/v1/search', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'Notion-Version': '2022-06-28',
        },
        body: JSON.stringify({
          query: input.query,
          page_size: input.pageSize ?? 10,
        }),
      });

      return {
        kind: 'search',
        results: (payload as { results?: Array<Record<string, unknown>> }).results ?? [],
      };
    }

    if (action === 'pages.create') {
      const input = z
        .object({
          parent: z.union([
            z.object({ database_id: z.string().trim().min(1) }),
            z.object({ page_id: z.string().trim().min(1) }),
          ]),
          properties: z.record(z.string(), z.unknown()),
          children: z.array(z.record(z.string(), z.unknown())).optional(),
        })
        .parse(parameters);

      const payload = await this.requestIntegrationJson('notion', 'https://api.notion.com/v1/pages', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${accessToken}`,
          Accept: 'application/json',
          'Content-Type': 'application/json',
          'Notion-Version': '2022-06-28',
        },
        body: JSON.stringify({
          parent: input.parent,
          properties: input.properties,
          children: input.children,
        }),
      });

      return {
        kind: 'pages.create',
        pageId: (payload as { id?: string }).id ?? null,
      };
    }

    if (action === 'databases.query') {
      const input = z
        .object({
          databaseId: z.string().trim().min(1),
          filter: z.record(z.string(), z.unknown()).optional(),
          sorts: z.array(z.record(z.string(), z.unknown())).optional(),
        })
        .parse(parameters);

      const payload = await this.requestIntegrationJson(
        'notion',
        `https://api.notion.com/v1/databases/${encodeURIComponent(input.databaseId)}/query`,
        {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${accessToken}`,
            Accept: 'application/json',
            'Content-Type': 'application/json',
            'Notion-Version': '2022-06-28',
          },
          body: JSON.stringify({
            filter: input.filter,
            sorts: input.sorts,
          }),
        }
      );

      return {
        kind: 'databases.query',
        results: (payload as { results?: Array<Record<string, unknown>> }).results ?? [],
      };
    }

    throw new ControlPlaneValidationError(`Unsupported Notion integration action: ${action}`);
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
      integrations: account.integrations ?? {},
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
