import { z } from 'zod';

export const controlPlanePlanIdSchema = z.enum([
  'local_byok',
  'cloud_assisted',
  'pro_builder',
  'team_business',
]);

export type ControlPlanePlanId = z.infer<typeof controlPlanePlanIdSchema>;

export const controlPlaneOwnerTypeSchema = z.enum(['individual', 'team', 'organization']);

export type ControlPlaneOwnerType = z.infer<typeof controlPlaneOwnerTypeSchema>;

export const controlPlaneAccountStatusSchema = z.enum([
  'trialing',
  'active',
  'past_due',
  'suspended',
  'canceled',
]);

export type ControlPlaneAccountStatus = z.infer<typeof controlPlaneAccountStatusSchema>;

export const controlPlaneUsageDomainSchema = z.enum([
  'inference',
  'retrieval',
  'integrations',
  'evaluation',
]);

export type ControlPlaneUsageDomain = z.infer<typeof controlPlaneUsageDomainSchema>;

export const controlPlaneTaskIntentSchema = z.enum([
  'direct_answer',
  'research',
  'comparison',
  'procedural',
  'personal_workflow',
]);

export type ControlPlaneTaskIntent = z.infer<typeof controlPlaneTaskIntentSchema>;

export const controlPlaneReasoningDepthSchema = z.enum(['shallow', 'standard', 'deep']);

export type ControlPlaneReasoningDepth = z.infer<typeof controlPlaneReasoningDepthSchema>;

export const controlPlaneRoutingModeSchema = z.enum([
  'local_only',
  'local_first',
  'balanced',
  'cloud_preferred',
]);

export type ControlPlaneRoutingMode = z.infer<typeof controlPlaneRoutingModeSchema>;

export const controlPlaneIntentConfidenceSchema = z.enum(['low', 'medium', 'high']);

export type ControlPlaneIntentConfidence = z.infer<typeof controlPlaneIntentConfidenceSchema>;

export const controlPlaneEvaluationQualitySchema = z.enum(['good', 'mixed', 'poor', 'skipped']);

export type ControlPlaneEvaluationQuality = z.infer<typeof controlPlaneEvaluationQualitySchema>;

export const controlPlaneEvaluationRetrievalSchema = z.object({
  shouldRetrieve: z.boolean(),
  searchAvailable: z.boolean(),
  rounds: z.number().int().nonnegative(),
  maxUrls: z.number().int().nonnegative(),
  sourceCount: z.number().int().nonnegative(),
  citationCount: z.number().int().nonnegative(),
});

export type ControlPlaneEvaluationRetrieval = z.infer<typeof controlPlaneEvaluationRetrievalSchema>;

export const controlPlaneEvaluationToolingSchema = z.object({
  enabled: z.boolean(),
  capabilityIds: z.array(z.string().min(1)),
  toolCallCount: z.number().int().nonnegative(),
  toolResultCount: z.number().int().nonnegative(),
});

export type ControlPlaneEvaluationTooling = z.infer<typeof controlPlaneEvaluationToolingSchema>;

export const controlPlaneEvaluationUsageSchema = z.object({
  inputTokens: z.number().int().nonnegative().optional(),
  outputTokens: z.number().int().nonnegative().optional(),
  totalTokens: z.number().int().nonnegative().optional(),
});

export type ControlPlaneEvaluationUsage = z.infer<typeof controlPlaneEvaluationUsageSchema>;

export const controlPlaneEvaluationModelSchema = z.object({
  provider: z.string().min(1),
  modelId: z.string().min(1),
});

export type ControlPlaneEvaluationModel = z.infer<typeof controlPlaneEvaluationModelSchema>;

export const controlPlaneEvaluationSignalDraftSchema = z.object({
  requestId: z.string().min(1).optional(),
  mode: z.enum(['speed', 'research']),
  surface: z.enum(['local', 'shared-vps', 'hosted']),
  model: controlPlaneEvaluationModelSchema,
  taskIntent: controlPlaneTaskIntentSchema,
  reasoningDepth: controlPlaneReasoningDepthSchema,
  routingMode: controlPlaneRoutingModeSchema,
  intentConfidence: controlPlaneIntentConfidenceSchema,
  retrieval: controlPlaneEvaluationRetrievalSchema,
  tooling: controlPlaneEvaluationToolingSchema,
  usage: controlPlaneEvaluationUsageSchema,
  latencyMs: z.number().int().nonnegative(),
  queryLength: z.number().int().nonnegative(),
  answerLength: z.number().int().nonnegative(),
  quality: controlPlaneEvaluationQualitySchema,
  promotionCandidate: z.boolean(),
  notes: z.array(z.string().min(1)).default([]),
});

export type ControlPlaneEvaluationSignalDraft = z.infer<typeof controlPlaneEvaluationSignalDraftSchema>;

export const controlPlaneEvaluationSignalSchema = controlPlaneEvaluationSignalDraftSchema.extend({
  signalId: z.string().min(1),
  accountId: z.string().min(1),
  createdAt: z.string(),
});

export type ControlPlaneEvaluationSignal = z.infer<typeof controlPlaneEvaluationSignalSchema>;

export const controlPlaneLearningArtifactTypeSchema = z.enum([
  'brain_model',
  'prompt_hint',
  'routing_hint',
  'tool_usage_pattern',
]);

export type ControlPlaneLearningArtifactType = z.infer<typeof controlPlaneLearningArtifactTypeSchema>;

export const controlPlaneConversationRoleSchema = z.enum(['user', 'assistant', 'system']);

export type ControlPlaneConversationRole = z.infer<typeof controlPlaneConversationRoleSchema>;

export const controlPlaneInteractionIntentSchema = z.enum([
  'direct_answer',
  'research',
  'tool_action',
  'follow_up_question',
]);

export type ControlPlaneInteractionIntent = z.infer<typeof controlPlaneInteractionIntentSchema>;

export const controlPlaneMemoryKindSchema = z.enum(['preference', 'project', 'routine', 'recent']);

export type ControlPlaneMemoryKind = z.infer<typeof controlPlaneMemoryKindSchema>;

export const controlPlaneMemoryItemSchema = z.object({
  memoryId: z.string().min(1),
  accountId: z.string().min(1),
  kind: controlPlaneMemoryKindSchema,
  title: z.string().min(1),
  summary: z.string().min(1),
  source: z.enum(['user', 'assistant', 'system', 'learning']).default('system'),
  threadId: z.string().min(1).optional(),
  projectKey: z.string().min(1).optional(),
  routineKey: z.string().min(1).optional(),
  confidence: z.number().min(0).max(1),
  pinned: z.boolean().default(false),
  promoted: z.boolean().default(false),
  promotedFromDraftId: z.string().min(1).optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
  lastUsedAt: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export type ControlPlaneMemoryItem = z.infer<typeof controlPlaneMemoryItemSchema>;

export const controlPlaneConversationMessageSchema = z.object({
  messageId: z.string().min(1),
  threadId: z.string().min(1),
  accountId: z.string().min(1),
  role: controlPlaneConversationRoleSchema,
  content: z.string().min(1),
  source: z.string().min(1),
  createdAt: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export type ControlPlaneConversationMessage = z.infer<typeof controlPlaneConversationMessageSchema>;

export const controlPlaneConversationThreadSchema = z.object({
  threadId: z.string().min(1),
  accountId: z.string().min(1),
  source: z.string().min(1),
  title: z.string().min(1),
  summary: z.string().min(1),
  intent: controlPlaneInteractionIntentSchema,
  status: z.enum(['active', 'closed', 'archived']).default('active'),
  messageCount: z.number().int().nonnegative(),
  createdAt: z.string(),
  updatedAt: z.string(),
  lastMessageAt: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export type ControlPlaneConversationThread = z.infer<typeof controlPlaneConversationThreadSchema>;

export const controlPlaneLearningDraftSchema = z.object({
  draftId: z.string().min(1),
  accountId: z.string().min(1),
  threadId: z.string().min(1).optional(),
  kind: z.enum(['preference', 'project', 'routine', 'research']),
  title: z.string().min(1),
  summary: z.string().min(1),
  body: z.string().min(1),
  status: z.enum(['draft', 'promoted', 'discarded']).default('draft'),
  promotedMemoryId: z.string().min(1).optional(),
  source: z.string().min(1),
  createdAt: z.string(),
  updatedAt: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export type ControlPlaneLearningDraft = z.infer<typeof controlPlaneLearningDraftSchema>;

export const controlPlaneLearningEventSchema = z.object({
  eventId: z.string().min(1),
  accountId: z.string().min(1),
  spaceId: z.string().min(1).optional(),
  requestId: z.string().min(1),
  source: z.string().min(1),
  input: z.string().min(1),
  intent: controlPlaneInteractionIntentSchema,
  taskType: controlPlaneTaskIntentSchema,
  plan: z.string().min(1),
  reasoningSteps: z.array(z.string().min(1)).default([]),
  reasoningTrace: z.array(z.string().min(1)).default([]),
  output: z.string(),
  betterOutput: z.string().default(''),
  success: z.boolean(),
  failureReason: z.string().min(1).optional(),
  feedback: z.record(z.string(), z.unknown()).default({}),
  latencyMs: z.number().int().nonnegative(),
  score: z.number().min(0).max(1),
  accepted: z.boolean().default(false),
  modelId: z.string().min(1).optional(),
  modelProvider: z.string().min(1).optional(),
  isSafeForLearning: z.boolean().default(false),
  createdAt: z.string(),
  updatedAt: z.string(),
  metadata: z.record(z.string(), z.unknown()).default({}),
});

export type ControlPlaneLearningEvent = z.infer<typeof controlPlaneLearningEventSchema>;

export const controlPlaneModelArtifactSchema = z.object({
  modelVersion: z.string().min(1),
  baseModel: z.string().min(1),
  spaceId: z.string().min(1).optional(),
  datasetSize: z.number().int().nonnegative(),
  loss: z.number().optional(),
  score: z.number().min(0).max(1).optional(),
  active: z.boolean(),
  artifactPath: z.string().min(1),
  artifactType: controlPlaneLearningArtifactTypeSchema,
  sourceEventIds: z.array(z.string().min(1)).default([]),
  confidenceScore: z.number().min(0).max(1),
  isSafeForLearning: z.boolean().default(false),
  metadata: z.record(z.string(), z.unknown()).default({}),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type ControlPlaneModelArtifact = z.infer<typeof controlPlaneModelArtifactSchema>;

export const controlPlaneInteractionStateSchema = z.object({
  threads: z.array(controlPlaneConversationThreadSchema).default([]),
  messages: z.array(controlPlaneConversationMessageSchema).default([]),
  memoryItems: z.array(controlPlaneMemoryItemSchema).default([]),
  learningDrafts: z.array(controlPlaneLearningDraftSchema).default([]),
});

export type ControlPlaneInteractionState = z.infer<typeof controlPlaneInteractionStateSchema>;

export const controlPlaneEntitlementsSchema = z.object({
  hostedAccess: z.boolean(),
  hostedUsageAccounting: z.boolean(),
  managedCredits: z.boolean(),
  cloudRouting: z.boolean(),
  advancedRouting: z.boolean(),
  teamGovernance: z.boolean(),
  hostedImprovementSignals: z.boolean(),
});

export type ControlPlaneEntitlements = z.infer<typeof controlPlaneEntitlementsSchema>;

export const controlPlaneRateCardSchema = z.record(z.string(), z.string());

export type ControlPlaneRateCard = z.infer<typeof controlPlaneRateCardSchema>;

export const controlPlaneRateLimitSchema = z.object({
  hostedRequestsPerMinute: z.number().int().nonnegative(),
  hostedToolCallsPerMinute: z.number().int().nonnegative(),
});

export type ControlPlaneRateLimit = z.infer<typeof controlPlaneRateLimitSchema>;

export const controlPlaneDailyLimitSchema = z.object({
  hostedRequestsPerDay: z.number().int().nonnegative(),
  hostedToolActionCallsPerDay: z.number().int().nonnegative(),
});

export type ControlPlaneDailyLimit = z.infer<typeof controlPlaneDailyLimitSchema>;

export const controlPlanePlanTierSchema = z.enum(['FREE', 'PRO', 'TEAM']);

export type ControlPlanePlanTier = z.infer<typeof controlPlanePlanTierSchema>;

export const controlPlanePlanTokenLimitsSchema = z.object({
  monthlyIncludedTokens: z.number().int().nonnegative(),
  maxTokensPerRequest: z.number().int().nonnegative(),
});

export type ControlPlanePlanTokenLimits = z.infer<typeof controlPlanePlanTokenLimitsSchema>;

export const controlPlanePlanModelAccessSchema = z.object({
  localModels: z.boolean(),
  hostedModels: z.boolean(),
  advancedModels: z.boolean(),
});

export type ControlPlanePlanModelAccess = z.infer<typeof controlPlanePlanModelAccessSchema>;

export const controlPlanePlanFeatureAccessSchema = z.object({
  hostedChat: z.boolean(),
  research: z.boolean(),
  integrations: z.boolean(),
  teamRuns: z.boolean(),
});

export type ControlPlanePlanFeatureAccess = z.infer<typeof controlPlanePlanFeatureAccessSchema>;

export const controlPlanePlanSchema = z.object({
  id: controlPlanePlanIdSchema,
  tier: controlPlanePlanTierSchema,
  title: z.string(),
  summary: z.string(),
  audience: z.string(),
  monthlyPriceTRY: z.string(),
  monthlyIncludedCredits: z.string(),
  tokenLimits: controlPlanePlanTokenLimitsSchema,
  modelAccess: controlPlanePlanModelAccessSchema,
  featureAccess: controlPlanePlanFeatureAccessSchema,
  entitlements: controlPlaneEntitlementsSchema,
  rateCard: controlPlaneRateCardSchema,
  rateLimits: controlPlaneRateLimitSchema,
  dailyLimits: controlPlaneDailyLimitSchema,
  upgradeTriggers: z.array(z.string()),
});

export type ControlPlanePlan = z.infer<typeof controlPlanePlanSchema>;

export const controlPlaneSubscriptionSchema = z.object({
  planId: controlPlanePlanIdSchema,
  status: controlPlaneAccountStatusSchema,
  provider: z.enum(['manual', 'iyzico']),
  providerCustomerRef: z.string().min(1).optional(),
  providerProductRef: z.string().min(1).optional(),
  providerPricingPlanRef: z.string().min(1).optional(),
  providerSubscriptionRef: z.string().min(1).optional(),
  providerStatus: z.string().min(1).optional(),
  syncState: z.enum(['unbound', 'pending', 'synced', 'failed']),
  retryCount: z.number().int().nonnegative(),
  lastSyncedAt: z.string().optional(),
  nextRetryAt: z.string().optional(),
  lastSyncError: z.string().optional(),
  currentPeriodStartedAt: z.string(),
  currentPeriodEndsAt: z.string(),
  creditsGrantedThisPeriod: z.string(),
  processedWebhookEventRefs: z.array(z.string().min(1)).default([]),
});

export type ControlPlaneSubscription = z.infer<typeof controlPlaneSubscriptionSchema>;

export const controlPlaneBillingBindingStatusSchema = z.enum([
  'unbound',
  'pending',
  'synced',
  'failed',
]);

export type ControlPlaneBillingBindingStatus = z.infer<typeof controlPlaneBillingBindingStatusSchema>;

export const controlPlaneBillingPlanBindingSchema = z.object({
  provider: z.literal('iyzico'),
  planId: controlPlanePlanIdSchema,
  productName: z.string().min(1),
  productReferenceCode: z.string().min(1).optional(),
  pricingPlanName: z.string().min(1),
  pricingPlanReferenceCode: z.string().min(1).optional(),
  currencyCode: z.enum(['TRY', 'USD', 'EUR']),
  paymentInterval: z.enum(['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY']),
  paymentIntervalCount: z.number().int().positive(),
  planPaymentType: z.literal('RECURRING'),
  syncState: controlPlaneBillingBindingStatusSchema,
  lastSyncedAt: z.string().optional(),
  lastSyncError: z.string().optional(),
});

export type ControlPlaneBillingPlanBinding = z.infer<typeof controlPlaneBillingPlanBindingSchema>;

export const controlPlaneBillingStateSchema = z.object({
  iyzico: z.object({
    plans: z.record(controlPlanePlanIdSchema, controlPlaneBillingPlanBindingSchema),
  }),
});

export type ControlPlaneBillingState = z.infer<typeof controlPlaneBillingStateSchema>;

export const controlPlaneUsageSnapshotStateSchema = z.enum([
  'ok',
  'daily_limit_reached',
  'monthly_credits_exhausted',
]);

export type ControlPlaneUsageSnapshotState = z.infer<typeof controlPlaneUsageSnapshotStateSchema>;

export const controlPlaneUsageSnapshotSchema = z.object({
  dayKey: z.string().min(1),
  resetAt: z.string(),
  dailyRequests: z.number().int().nonnegative(),
  dailyRequestsLimit: z.number().int().nonnegative(),
  remainingRequests: z.number().int().nonnegative(),
  dailyHostedToolActionCalls: z.number().int().nonnegative(),
  dailyHostedToolActionCallsLimit: z.number().int().nonnegative(),
  remainingHostedToolActionCalls: z.number().int().nonnegative(),
  dailyTokens: z.number().int().nonnegative(),
  dailyTokensLimit: z.number().int().nonnegative(),
  remainingTokens: z.number().int().nonnegative(),
  monthlyCreditsRemaining: z.string(),
  monthlyCreditsBurned: z.string(),
  state: controlPlaneUsageSnapshotStateSchema,
});

export type ControlPlaneUsageSnapshot = z.infer<typeof controlPlaneUsageSnapshotSchema>;

export const controlPlaneAccountSchema = z.object({
  accountId: z.string().min(1),
  ownerUserId: z.string().min(1).optional(),
  displayName: z.string().min(1),
  ownerType: controlPlaneOwnerTypeSchema,
  billingCustomerRef: z.string().min(1).optional(),
  status: controlPlaneAccountStatusSchema,
  subscription: controlPlaneSubscriptionSchema,
  entitlements: controlPlaneEntitlementsSchema,
  balanceCredits: z.string(),
  usageTotals: z.record(z.string(), z.string()),
  usageSnapshot: controlPlaneUsageSnapshotSchema,
  integrations: z.record(z.string(), z.lazy(() => controlPlaneIntegrationSchema)).default({}),
  interactionState: controlPlaneInteractionStateSchema.default({
    threads: [],
    messages: [],
    memoryItems: [],
    learningDrafts: [],
  }),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type ControlPlaneAccount = z.infer<typeof controlPlaneAccountSchema>;

export const controlPlaneLegacyAccountSchema = controlPlaneAccountSchema.omit({
  usageSnapshot: true,
});

export type ControlPlaneLegacyAccount = z.infer<typeof controlPlaneLegacyAccountSchema>;

export const controlPlaneIntegrationSummarySchema = z.object({
  total: z.number().int().nonnegative(),
  connected: z.number().int().nonnegative(),
  needsAttention: z.number().int().nonnegative(),
});

export type ControlPlaneIntegrationSummary = z.infer<typeof controlPlaneIntegrationSummarySchema>;

export const controlPlaneAccountPublicSchema = controlPlaneAccountSchema.omit({
  interactionState: true,
  integrations: true,
}).extend({
  integrations: z.record(z.string(), z.lazy(() => controlPlaneIntegrationPublicSchema)).default({}),
  integrationSummary: z.lazy(() => controlPlaneIntegrationSummarySchema),
});

export type ControlPlaneAccountPublic = z.infer<typeof controlPlaneAccountPublicSchema>;

export const controlPlaneUserStatusSchema = z.enum(['active', 'disabled']);

export type ControlPlaneUserStatus = z.infer<typeof controlPlaneUserStatusSchema>;

export const controlPlaneUserRoleSchema = z.enum(['owner', 'admin', 'member']);

export type ControlPlaneUserRole = z.infer<typeof controlPlaneUserRoleSchema>;

export const controlPlaneUserSchema = z.object({
  userId: z.string().min(1),
  accountId: z.string().min(1),
  email: z.string().email(),
  displayName: z.string().min(1),
  ownerType: controlPlaneOwnerTypeSchema,
  role: controlPlaneUserRoleSchema.default('owner'),
  passwordSalt: z.string().min(1),
  passwordHash: z.string().min(1),
  status: controlPlaneUserStatusSchema,
  createdAt: z.string(),
  updatedAt: z.string(),
  lastLoginAt: z.string().optional(),
});

export type ControlPlaneUser = z.infer<typeof controlPlaneUserSchema>;

export const controlPlaneLedgerStatusSchema = z.enum(['posted', 'denied']);

export type ControlPlaneLedgerStatus = z.infer<typeof controlPlaneLedgerStatusSchema>;

export const controlPlaneLedgerKindSchema = z.enum([
  'subscription_grant',
  'usage_charge',
  'usage_denial',
  'adjustment',
]);

export type ControlPlaneLedgerKind = z.infer<typeof controlPlaneLedgerKindSchema>;

export const controlPlaneLedgerSourceSchema = z.enum([
  'hosted_web',
  'hosted_api',
  'mcp',
  'admin',
]);

export type ControlPlaneLedgerSource = z.infer<typeof controlPlaneLedgerSourceSchema>;

export const controlPlaneLedgerEntrySchema = z.object({
  entryId: z.string().min(1),
  accountId: z.string().min(1),
  kind: controlPlaneLedgerKindSchema,
  status: controlPlaneLedgerStatusSchema,
  domain: controlPlaneUsageDomainSchema.optional(),
  creditsDelta: z.string(),
  balanceAfter: z.string(),
  source: controlPlaneLedgerSourceSchema.optional(),
  requestId: z.string().min(1).optional(),
  note: z.string().min(1).optional(),
  createdAt: z.string(),
});

export type ControlPlaneLedgerEntry = z.infer<typeof controlPlaneLedgerEntrySchema>;

export const controlPlaneNotificationLevelSchema = z.enum(['info', 'warning', 'error']);

export type ControlPlaneNotificationLevel = z.infer<typeof controlPlaneNotificationLevelSchema>;

export const controlPlaneNotificationKindSchema = z.enum([
  'product_notice',
  'billing_notice',
  'maintenance_notice',
  'release_notice',
  'entitlement_notice',
]);

export type ControlPlaneNotificationKind = z.infer<typeof controlPlaneNotificationKindSchema>;

export const controlPlaneNotificationSchema = z.object({
  notificationId: z.string().min(1),
  accountId: z.string().min(1),
  title: z.string().min(1),
  body: z.string().min(1),
  kind: controlPlaneNotificationKindSchema,
  level: controlPlaneNotificationLevelSchema,
  seenAt: z.string().optional(),
  createdAt: z.string(),
});

export type ControlPlaneNotification = z.infer<typeof controlPlaneNotificationSchema>;

export const controlPlaneIntegrationProviderSchema = z.enum(['google', 'github', 'notion']);

export type ControlPlaneIntegrationProvider = z.infer<typeof controlPlaneIntegrationProviderSchema>;

export const controlPlaneIntegrationStatusSchema = z.enum([
  'disconnected',
  'connecting',
  'connected',
  'expired',
  'error',
  'revoked',
]);

export type ControlPlaneIntegrationStatus = z.infer<typeof controlPlaneIntegrationStatusSchema>;

export const controlPlaneIntegrationSurfaceSchema = z.enum(['gmail', 'calendar', 'github', 'notion']);

export type ControlPlaneIntegrationSurface = z.infer<typeof controlPlaneIntegrationSurfaceSchema>;

export const controlPlaneIntegrationSchema = z.object({
  integrationId: z.string().min(1),
  accountId: z.string().min(1),
  provider: controlPlaneIntegrationProviderSchema,
  displayName: z.string().min(1),
  status: controlPlaneIntegrationStatusSchema,
  scopes: z.array(z.string().min(1)).default([]),
  surfaces: z.array(controlPlaneIntegrationSurfaceSchema).default([]),
  externalAccountId: z.string().min(1).optional(),
  externalAccountLabel: z.string().min(1).optional(),
  accessTokenCiphertext: z.string().min(1).optional(),
  refreshTokenCiphertext: z.string().min(1).optional(),
  idTokenCiphertext: z.string().min(1).optional(),
  expiresAt: z.string().optional(),
  lastSyncedAt: z.string().optional(),
  lastError: z.string().optional(),
  metadata: z.record(z.string(), z.unknown()).default({}),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type ControlPlaneIntegration = z.infer<typeof controlPlaneIntegrationSchema>;

export const controlPlaneIntegrationPublicSchema = controlPlaneIntegrationSchema.omit({
  accessTokenCiphertext: true,
  refreshTokenCiphertext: true,
  idTokenCiphertext: true,
});

export type ControlPlaneIntegrationPublic = z.infer<typeof controlPlaneIntegrationPublicSchema>;

export const controlPlaneDeviceStatusSchema = z.enum(['pending', 'active', 'revoked', 'expired']);

export type ControlPlaneDeviceStatus = z.infer<typeof controlPlaneDeviceStatusSchema>;

export const controlPlaneDeviceMetadataSchema = z.record(z.string(), z.unknown());

export type ControlPlaneDeviceMetadata = z.infer<typeof controlPlaneDeviceMetadataSchema>;

export const controlPlaneDeviceLinkSchema = z.object({
  linkCode: z.string().min(1),
  accountId: z.string().min(1),
  userId: z.string().min(1),
  deviceLabel: z.string().min(1),
  status: z.enum(['pending', 'complete', 'consumed', 'expired']),
  expiresAt: z.string(),
  createdAt: z.string(),
  completedAt: z.string().optional(),
  consumedAt: z.string().optional(),
  deviceToken: z.string().min(1).optional(),
});

export type ControlPlaneDeviceLink = z.infer<typeof controlPlaneDeviceLinkSchema>;

export const controlPlaneDeviceSchema = z.object({
  deviceId: z.string().min(1),
  accountId: z.string().min(1),
  userId: z.string().min(1),
  deviceLabel: z.string().min(1),
  status: controlPlaneDeviceStatusSchema,
  deviceToken: z.string().min(1),
  metadata: controlPlaneDeviceMetadataSchema.default({}),
  lastSeenReleaseTag: z.string().min(1).optional(),
  lastSeenAt: z.string().optional(),
  linkedAt: z.string(),
  revokedAt: z.string().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type ControlPlaneDevice = z.infer<typeof controlPlaneDeviceSchema>;

export const controlPlaneStateV1Schema = z.object({
  version: z.literal(1),
  accounts: z.record(z.string(), controlPlaneLegacyAccountSchema),
  ledger: z.array(controlPlaneLedgerEntrySchema),
});

export const controlPlaneStateV2Schema = z.object({
  version: z.literal(2),
  billing: controlPlaneBillingStateSchema,
  users: z.record(z.string(), controlPlaneUserSchema),
  accounts: z.record(z.string(), controlPlaneLegacyAccountSchema),
  ledger: z.array(controlPlaneLedgerEntrySchema),
  notifications: z.array(controlPlaneNotificationSchema).default([]),
});

export const controlPlaneStateV3Schema = z.object({
  version: z.literal(3),
  billing: controlPlaneBillingStateSchema,
  users: z.record(z.string(), controlPlaneUserSchema),
  accounts: z.record(z.string(), controlPlaneLegacyAccountSchema),
  ledger: z.array(controlPlaneLedgerEntrySchema),
  notifications: z.array(controlPlaneNotificationSchema).default([]),
  devices: z.record(z.string(), controlPlaneDeviceSchema).default({}),
  deviceLinks: z.record(z.string(), controlPlaneDeviceLinkSchema).default({}),
  evaluationSignals: z.array(controlPlaneEvaluationSignalSchema).default([]),
});

export const controlPlaneStateV4Schema = z.object({
  version: z.literal(4),
  billing: controlPlaneBillingStateSchema,
  users: z.record(z.string(), controlPlaneUserSchema),
  accounts: z.record(z.string(), controlPlaneAccountSchema),
  ledger: z.array(controlPlaneLedgerEntrySchema),
  notifications: z.array(controlPlaneNotificationSchema).default([]),
  devices: z.record(z.string(), controlPlaneDeviceSchema).default({}),
  deviceLinks: z.record(z.string(), controlPlaneDeviceLinkSchema).default({}),
  evaluationSignals: z.array(controlPlaneEvaluationSignalSchema).default([]),
});

export const controlPlaneStateV5Schema = z.object({
  version: z.literal(5),
  billing: controlPlaneBillingStateSchema,
  users: z.record(z.string(), controlPlaneUserSchema),
  accounts: z.record(z.string(), controlPlaneAccountSchema),
  ledger: z.array(controlPlaneLedgerEntrySchema),
  notifications: z.array(controlPlaneNotificationSchema).default([]),
  devices: z.record(z.string(), controlPlaneDeviceSchema).default({}),
  deviceLinks: z.record(z.string(), controlPlaneDeviceLinkSchema).default({}),
  evaluationSignals: z.array(controlPlaneEvaluationSignalSchema).default([]),
});

export const controlPlaneStateV6Schema = z.object({
  version: z.literal(6),
  billing: controlPlaneBillingStateSchema,
  users: z.record(z.string(), controlPlaneUserSchema),
  accounts: z.record(z.string(), controlPlaneAccountSchema),
  ledger: z.array(controlPlaneLedgerEntrySchema),
  notifications: z.array(controlPlaneNotificationSchema).default([]),
  devices: z.record(z.string(), controlPlaneDeviceSchema).default({}),
  deviceLinks: z.record(z.string(), controlPlaneDeviceLinkSchema).default({}),
  evaluationSignals: z.array(controlPlaneEvaluationSignalSchema).default([]),
  learningEvents: z.array(controlPlaneLearningEventSchema).default([]),
});

export const controlPlaneStateSchema = z.union([
  controlPlaneStateV1Schema,
  controlPlaneStateV2Schema,
  controlPlaneStateV3Schema,
  controlPlaneStateV4Schema,
  controlPlaneStateV5Schema,
  controlPlaneStateV6Schema,
]);

export type ControlPlaneState = {
  version: 6;
  billing: ControlPlaneBillingState;
  users: Record<string, ControlPlaneUser>;
  accounts: Record<string, ControlPlaneAccount>;
  ledger: ControlPlaneLedgerEntry[];
  notifications: ControlPlaneNotification[];
  devices: Record<string, ControlPlaneDevice>;
  deviceLinks: Record<string, ControlPlaneDeviceLink>;
  evaluationSignals: ControlPlaneEvaluationSignal[];
  learningEvents: ControlPlaneLearningEvent[];
};

export const controlPlaneAccountUpsertSchema = z.object({
  displayName: z.string().trim().min(1),
  ownerType: controlPlaneOwnerTypeSchema.default('individual'),
  planId: controlPlanePlanIdSchema,
  billingCustomerRef: z.string().trim().min(1).optional(),
  ownerUserId: z.string().trim().min(1).optional(),
});

export type ControlPlaneAccountUpsertInput = z.infer<typeof controlPlaneAccountUpsertSchema>;

export const controlPlaneIdentityRegisterSchema = z.object({
  email: z.string().trim().email(),
  password: z.string().min(12),
  displayName: z.string().trim().min(1),
  ownerType: controlPlaneOwnerTypeSchema.default('individual'),
  planId: controlPlanePlanIdSchema,
});

export type ControlPlaneIdentityRegisterInput = z.infer<typeof controlPlaneIdentityRegisterSchema>;

export const controlPlaneUsageInputSchema = z.object({
  domain: controlPlaneUsageDomainSchema,
  units: z.number().positive(),
  tokens: z.number().int().nonnegative().optional(),
  source: controlPlaneLedgerSourceSchema.default('hosted_api'),
  requestId: z.string().trim().min(1).optional(),
  note: z.string().trim().min(1).optional(),
});

export type ControlPlaneUsageInput = z.infer<typeof controlPlaneUsageInputSchema>;

export const controlPlaneUsageQuoteSchema = z.object({
  accountId: z.string(),
  planId: controlPlanePlanIdSchema,
  domain: controlPlaneUsageDomainSchema,
  units: z.number().positive(),
  creditsDelta: z.string(),
  balanceBefore: z.string(),
  balanceAfter: z.string(),
  allowed: z.boolean(),
  denialReason: z.string().optional(),
  resetAt: z.string().optional(),
  remainingRequests: z.number().int().nonnegative().optional(),
  remainingHostedToolActionCalls: z.number().int().nonnegative().optional(),
  remainingTokens: z.number().int().nonnegative().optional(),
  monthlyCreditsRemaining: z.string().optional(),
  requestTokens: z.number().int().nonnegative().optional(),
});

export type ControlPlaneUsageQuote = z.infer<typeof controlPlaneUsageQuoteSchema>;

export const controlPlaneHostedSessionSchema = z.object({
  userId: z.string().min(1),
  email: z.string().email(),
  name: z.string().min(1),
  accountId: z.string().min(1),
  ownerType: controlPlaneOwnerTypeSchema,
  role: controlPlaneUserRoleSchema,
  planId: controlPlanePlanIdSchema,
  accountStatus: controlPlaneAccountStatusSchema,
  subscriptionStatus: controlPlaneAccountStatusSchema,
  subscriptionSyncState: controlPlaneBillingBindingStatusSchema,
  hostedAccess: z.boolean(),
  hostedUsageAccounting: z.boolean(),
  balanceCredits: z.string(),
  tokenBalance: z.string(),
  deviceCount: z.number().int().nonnegative(),
  activeDeviceCount: z.number().int().nonnegative(),
});

export type ControlPlaneHostedSession = z.infer<typeof controlPlaneHostedSessionSchema>;

export const controlPlaneDeviceSummarySchema = z.object({
  total: z.number().int().nonnegative(),
  pending: z.number().int().nonnegative(),
  active: z.number().int().nonnegative(),
  revoked: z.number().int().nonnegative(),
  expired: z.number().int().nonnegative(),
});

export type ControlPlaneDeviceSummary = z.infer<typeof controlPlaneDeviceSummarySchema>;

export const controlPlaneHostedDeviceSchema = z.object({
  deviceId: z.string().min(1),
  deviceLabel: z.string().min(1),
  status: controlPlaneDeviceStatusSchema,
  linkedAt: z.string(),
  lastSeenAt: z.string().optional(),
  lastSeenReleaseTag: z.string().min(1).optional(),
  revokedAt: z.string().optional(),
  createdAt: z.string(),
  updatedAt: z.string(),
});

export type ControlPlaneHostedDevice = z.infer<typeof controlPlaneHostedDeviceSchema>;

export const controlPlaneHostedDevicePublicSchema = controlPlaneHostedDeviceSchema;
export type ControlPlaneHostedDevicePublic = z.infer<typeof controlPlaneHostedDevicePublicSchema>;

export const controlPlaneHostedAccountSchema = controlPlaneAccountPublicSchema.extend({
  plan: controlPlanePlanSchema,
  processedWebhookEventCount: z.number().int().nonnegative(),
  deviceSummary: controlPlaneDeviceSummarySchema,
});

export type ControlPlaneHostedAccount = z.infer<typeof controlPlaneHostedAccountSchema>;

export const controlPlaneHostedProfileSchema = z.object({
  session: controlPlaneHostedSessionSchema,
  user: controlPlaneUserSchema.pick({
    userId: true,
    email: true,
    displayName: true,
    ownerType: true,
    role: true,
    status: true,
  }).optional(),
  account: controlPlaneHostedAccountSchema,
});

export type ControlPlaneHostedProfile = z.infer<typeof controlPlaneHostedProfileSchema>;

export const controlPlaneHostedPanelSchema = z.object({
  session: controlPlaneHostedSessionSchema,
  profile: controlPlaneHostedProfileSchema,
  account: controlPlaneHostedAccountSchema,
  devices: z.array(controlPlaneHostedDevicePublicSchema),
});

export type ControlPlaneHostedPanel = z.infer<typeof controlPlaneHostedPanelSchema>;

export const controlPlaneDeviceLinkStartSchema = z.object({
  deviceLabel: z.string().trim().min(1),
});

export type ControlPlaneDeviceLinkStartInput = z.infer<typeof controlPlaneDeviceLinkStartSchema>;

export const controlPlaneDeviceLinkCompleteSchema = z.object({
  linkCode: z.string().trim().min(6),
  deviceLabel: z.string().trim().min(1),
  metadata: controlPlaneDeviceMetadataSchema.default({}),
});

export type ControlPlaneDeviceLinkCompleteInput = z.infer<typeof controlPlaneDeviceLinkCompleteSchema>;

export const controlPlaneIntegrationConnectStartSchema = z.object({
  provider: controlPlaneIntegrationProviderSchema,
  returnTo: z.string().trim().min(1).optional(),
});

export type ControlPlaneIntegrationConnectStartInput = z.infer<typeof controlPlaneIntegrationConnectStartSchema>;

export const controlPlaneIntegrationCallbackSchema = z.object({
  code: z.string().trim().min(1),
  state: z.string().trim().min(1),
});

export type ControlPlaneIntegrationCallbackInput = z.infer<typeof controlPlaneIntegrationCallbackSchema>;

export const controlPlaneIntegrationDisconnectSchema = z.object({
  integrationId: z.string().trim().min(1),
});

export type ControlPlaneIntegrationDisconnectInput = z.infer<typeof controlPlaneIntegrationDisconnectSchema>;

export const controlPlaneIntegrationActionSchema = z.object({
  provider: controlPlaneIntegrationProviderSchema,
  integrationId: z.string().trim().min(1).optional(),
  action: z.string().trim().min(1),
  parameters: z.record(z.string(), z.unknown()).default({}),
});

export type ControlPlaneIntegrationActionInput = z.infer<typeof controlPlaneIntegrationActionSchema>;

export const controlPlaneDeviceBootstrapSchema = z.object({
  deviceToken: z.string().min(1),
});

export type ControlPlaneDeviceBootstrapInput = z.infer<typeof controlPlaneDeviceBootstrapSchema>;

export const controlPlaneDevicePushSchema = z.object({
  deviceToken: z.string().min(1),
  metadata: controlPlaneDeviceMetadataSchema.default({}),
  lastSeenReleaseTag: z.string().trim().min(1).optional(),
});

export type ControlPlaneDevicePushInput = z.infer<typeof controlPlaneDevicePushSchema>;

export const controlPlaneReleasePlatformSchema = z.enum(['macos', 'linux', 'windows']);

export type ControlPlaneReleasePlatform = z.infer<typeof controlPlaneReleasePlatformSchema>;

export const controlPlaneReleaseArchitectureSchema = z.enum(['arm64', 'x64']);

export type ControlPlaneReleaseArchitecture = z.infer<typeof controlPlaneReleaseArchitectureSchema>;

export const controlPlaneReleaseFormatSchema = z.enum(['zip', 'tar.gz']);

export type ControlPlaneReleaseFormat = z.infer<typeof controlPlaneReleaseFormatSchema>;

export const controlPlaneReleaseAssetSchema = z.object({
  name: z.string().min(1),
  size: z.number().nonnegative(),
  browserDownloadUrl: z.string().url(),
});

export type ControlPlaneReleaseAsset = z.infer<typeof controlPlaneReleaseAssetSchema>;

export const controlPlaneReleaseTargetSchema = z.object({
  platform: controlPlaneReleasePlatformSchema,
  architecture: controlPlaneReleaseArchitectureSchema,
  format: controlPlaneReleaseFormatSchema,
  name: z.string().min(1),
  browserDownloadUrl: z.string().url(),
  size: z.number().nonnegative(),
  label: z.string().min(1),
});

export type ControlPlaneReleaseTarget = z.infer<typeof controlPlaneReleaseTargetSchema>;

export const controlPlaneReleaseSnapshotSchema = z.object({
  repository: z.string().min(1),
  tagName: z.string().min(1),
  name: z.string().min(1).optional(),
  publishedAt: z.string(),
  url: z.string().url(),
  htmlUrl: z.string().url(),
  assets: z.array(controlPlaneReleaseAssetSchema),
  targets: z.array(controlPlaneReleaseTargetSchema).default([]),
  requiredAssets: z.array(z.string().min(1)),
  complete: z.boolean(),
});

export type ControlPlaneReleaseSnapshot = z.infer<typeof controlPlaneReleaseSnapshotSchema>;
