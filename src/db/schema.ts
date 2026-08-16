import { relations, sql } from "drizzle-orm";
import {
  type AnyPgColumn,
  boolean,
  customType,
  date,
  index,
  integer,
  jsonb,
  pgEnum,
  pgTable,
  serial,
  text,
  timestamp,
  uniqueIndex,
  uuid,
  varchar,
} from "drizzle-orm/pg-core";
import {
  aiInvocationStatusValues,
  aiProviderValues,
  auditActorTypeValues,
  auditStatusValues,
  brainScopeValues,
  artifactKindValues,
  chatMessageRoleValues,
  chatMessageStatusValues,
  chatSessionSourceValues,
  chatSessionStatusValues,
  connectionProviderValues,
  datasetFormatValues,
  datasetSourceValues,
  datasetStatusValues,
  deviceTypeValues,
  integrationAuthTypeValues,
  integrationConnectionStatusValues,
  knowledgeDocumentStatusValues,
  knowledgeSourceTypeValues,
  mcpAuthTypeValues,
  mcpServerStatusValues,
  mcpTransportValues,
  modelArtifactStatusValues,
  oauthStateStatusValues,
  pairSessionStatusValues,
  runtimeConnectionStatusValues,
  sessionGoalScheduleHintValues,
  sessionGoalStatusValues,
  subscriptionStatusValues,
  taskStatusValues,
  trainingJobKindValues,
  trainingJobStatusValues,
  userRoleValues,
} from "../contracts/domain.js";

const vector384 = customType<{ data: string | null }>({
  dataType() {
    return "vector(384)";
  },
});

export const deviceTypeEnum = pgEnum("device_type", deviceTypeValues);
export const pairSessionStatusEnum = pgEnum("pair_session_status", pairSessionStatusValues);
export const runtimeConnectionStatusEnum = pgEnum("runtime_connection_status", runtimeConnectionStatusValues);
export const taskStatusEnum = pgEnum("task_status", taskStatusValues);
export const artifactKindEnum = pgEnum("artifact_kind", artifactKindValues);
export const subscriptionStatusEnum = pgEnum("subscription_status", subscriptionStatusValues);
export const aiProviderEnum = pgEnum("ai_provider", aiProviderValues);
export const userRoleEnum = pgEnum("user_role", userRoleValues);
export const connectionProviderEnum = pgEnum("connection_provider", connectionProviderValues);
export const integrationAuthTypeEnum = pgEnum("integration_auth_type", integrationAuthTypeValues);
export const integrationConnectionStatusEnum = pgEnum("integration_connection_status", integrationConnectionStatusValues);
export const oauthStateStatusEnum = pgEnum("oauth_state_status", oauthStateStatusValues);
export const mcpTransportEnum = pgEnum("mcp_transport", mcpTransportValues);
export const mcpAuthTypeEnum = pgEnum("mcp_auth_type", mcpAuthTypeValues);
export const mcpServerStatusEnum = pgEnum("mcp_server_status", mcpServerStatusValues);
export const auditActorTypeEnum = pgEnum("audit_actor_type", auditActorTypeValues);
export const auditStatusEnum = pgEnum("audit_status", auditStatusValues);
export const aiInvocationStatusEnum = pgEnum("ai_invocation_status", aiInvocationStatusValues);
export const brainScopeEnum = pgEnum("brain_scope", brainScopeValues);
export const datasetSourceEnum = pgEnum("dataset_source", datasetSourceValues);
export const datasetFormatEnum = pgEnum("dataset_format", datasetFormatValues);
export const datasetStatusEnum = pgEnum("dataset_status", datasetStatusValues);
export const trainingJobKindEnum = pgEnum("training_job_kind", trainingJobKindValues);
export const trainingJobStatusEnum = pgEnum("training_job_status", trainingJobStatusValues);
export const modelArtifactStatusEnum = pgEnum("model_artifact_status", modelArtifactStatusValues);
export const knowledgeDocumentStatusEnum = pgEnum("knowledge_document_status", knowledgeDocumentStatusValues);
export const knowledgeSourceTypeEnum = pgEnum("knowledge_source_type", knowledgeSourceTypeValues);
export const chatSessionSourceEnum = pgEnum("chat_session_source", chatSessionSourceValues);
export const chatSessionStatusEnum = pgEnum("chat_session_status", chatSessionStatusValues);
export const chatMessageRoleEnum = pgEnum("chat_message_role", chatMessageRoleValues);
export const chatMessageStatusEnum = pgEnum("chat_message_status", chatMessageStatusValues);
export const sessionGoalStatusEnum = pgEnum("session_goal_status", sessionGoalStatusValues);
export const sessionGoalScheduleHintEnum = pgEnum(
  "session_goal_schedule_hint",
  sessionGoalScheduleHintValues,
);
export const usageWindowTypeEnum = pgEnum("usage_window_type", ["daily", "weekly"]);

export const users = pgTable(
  "users",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    email: varchar("email", { length: 320 }).notNull().unique(),
    identityId: uuid("identity_id").references((): AnyPgColumn => userIdentityHistory.id, {
      onDelete: "set null",
    }),
    passwordHash: text("password_hash").notNull(),
    displayName: varchar("display_name", { length: 120 }),
    role: userRoleEnum("role").notNull().default("user"),
    approvalMode: varchar("approval_mode", { length: 32 })
      .notNull()
      .default("read_only_auto"),
    twoFactorEnabled: boolean("two_factor_enabled").notNull().default(false),
    twoFactorSecretEncrypted: text("two_factor_secret_encrypted"),
    twoFactorConfirmedAt: timestamp("two_factor_confirmed_at", { withTimezone: true }),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    emailIdx: index("users_email_idx").on(table.email),
    identityIdx: index("users_identity_idx").on(table.identityId),
    deletedAtIdx: index("users_deleted_at_idx").on(table.deletedAt),
  }),
);

export const userIdentityHistory = pgTable(
  "user_identity_history",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    normalizedEmail: varchar("normalized_email", { length: 320 }).notNull().unique(),
    firstUserId: uuid("first_user_id").references((): AnyPgColumn => users.id, {
      onDelete: "set null",
    }),
    latestUserId: uuid("latest_user_id").references((): AnyPgColumn => users.id, {
      onDelete: "set null",
    }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    normalizedEmailIdx: uniqueIndex("user_identity_history_normalized_email_uidx").on(
      table.normalizedEmail,
    ),
    latestUserIdx: index("user_identity_history_latest_user_idx").on(table.latestUserId),
  }),
);

export const userAvatars = pgTable(
  "user_avatars",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    mimeType: varchar("mime_type", { length: 120 }).notNull(),
    dataBase64: text("data_base64").notNull(),
    byteLength: integer("byte_length").notNull().default(0),
    version: integer("version").notNull().default(1),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: uniqueIndex("user_avatars_user_uidx").on(table.userId),
  }),
);

export const sessions = pgTable(
  "sessions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    refreshTokenHash: text("refresh_token_hash").notNull(),
    userAgent: text("user_agent"),
    ipAddress: varchar("ip_address", { length: 64 }),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    revokedAt: timestamp("revoked_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    lastUsedAt: timestamp("last_used_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("sessions_user_idx").on(table.userId),
  }),
);

export const authIdentities = pgTable(
  "auth_identities",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: connectionProviderEnum("provider").notNull(),
    providerSubject: varchar("provider_subject", { length: 160 }).notNull(),
    email: varchar("email", { length: 320 }),
    displayName: varchar("display_name", { length: 120 }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("auth_identities_user_idx").on(table.userId),
    providerIdx: index("auth_identities_provider_idx").on(table.provider),
    providerSubjectUniqueIdx: uniqueIndex("auth_identities_provider_subject_uidx").on(
      table.provider,
      table.providerSubject,
    ),
    userProviderUniqueIdx: uniqueIndex("auth_identities_user_provider_uidx").on(table.userId, table.provider),
  }),
);

export const devices = pgTable(
  "devices",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id").references(() => users.id, { onDelete: "set null" }),
    type: deviceTypeEnum("type").notNull(),
    externalDeviceId: varchar("external_device_id", { length: 160 }),
    label: varchar("label", { length: 120 }).notNull(),
    platform: varchar("platform", { length: 120 }).notNull(),
    runtimeVersion: varchar("runtime_version", { length: 80 }),
    appVersion: varchar("app_version", { length: 80 }),
    clientMetadata: jsonb("client_metadata").notNull().default(sql`'{}'::jsonb`),
    pushToken: text("push_token"),
    pushProvider: varchar("push_provider", { length: 40 }),
    pushTokenUpdatedAt: timestamp("push_token_updated_at", { withTimezone: true }),
    pushInvalidatedAt: timestamp("push_invalidated_at", { withTimezone: true }),
    notificationAuthorizationStatus: varchar("notification_authorization_status", {
      length: 40,
    }),
    deviceKeyHash: text("device_key_hash"),
    isActive: boolean("is_active").notNull().default(true),
    pairedAt: timestamp("paired_at", { withTimezone: true }),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("devices_user_idx").on(table.userId),
    typeIdx: index("devices_type_idx").on(table.type),
    externalDeviceIdx: index("devices_external_device_idx").on(table.externalDeviceId),
    userExternalDeviceUniqueIdx: uniqueIndex("devices_user_type_external_device_uidx").on(
      table.userId,
      table.type,
      table.externalDeviceId,
    ),
  }),
);

export const pairSessions = pgTable(
  "pair_sessions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    desktopDeviceId: uuid("desktop_device_id")
      .notNull()
      .references(() => devices.id, { onDelete: "cascade" }),
    claimedByUserId: uuid("claimed_by_user_id").references(() => users.id, { onDelete: "set null" }),
    status: pairSessionStatusEnum("status").notNull().default("pending"),
    pairingCode: varchar("pairing_code", { length: 24 }).notNull().unique(),
    pairingTokenHash: text("pairing_token_hash").notNull(),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    claimedAt: timestamp("claimed_at", { withTimezone: true }),
    consumedAt: timestamp("consumed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    desktopIdx: index("pair_sessions_desktop_idx").on(table.desktopDeviceId),
    statusIdx: index("pair_sessions_status_idx").on(table.status),
  }),
);

export const runtimeConnections = pgTable(
  "runtime_connections",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    deviceId: uuid("device_id")
      .notNull()
      .references(() => devices.id, { onDelete: "cascade" }),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    status: runtimeConnectionStatusEnum("status").notNull().default("online"),
    socketSessionId: varchar("socket_session_id", { length: 120 }),
    currentTaskId: uuid("current_task_id"),
    capabilities: jsonb("capabilities").notNull().default(sql`'[]'::jsonb`),
    capabilityStates: jsonb("capability_states").notNull().default(sql`'{}'::jsonb`),
    connectedAt: timestamp("connected_at", { withTimezone: true }).notNull().defaultNow(),
    lastHeartbeatAt: timestamp("last_heartbeat_at", { withTimezone: true }).notNull().defaultNow(),
    disconnectedAt: timestamp("disconnected_at", { withTimezone: true }),
  },
  (table) => ({
    deviceIdx: index("runtime_connections_device_idx").on(table.deviceId),
    userIdx: index("runtime_connections_user_idx").on(table.userId),
  }),
);

export const operatorRuns = pgTable(
  "operator_runs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    deviceId: uuid("device_id")
      .notNull()
      .references(() => devices.id, { onDelete: "cascade" }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    runKey: varchar("run_key", { length: 120 }).notNull(),
    task: text("task").notNull(),
    status: varchar("status", { length: 40 }).notNull().default("running"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("operator_runs_user_idx").on(table.userId),
    deviceIdx: index("operator_runs_device_idx").on(table.deviceId),
    taskIdx: index("operator_runs_task_idx").on(table.taskId),
    runKeyIdx: uniqueIndex("operator_runs_run_key_uidx").on(table.runKey),
  }),
);

export const screenObservations = pgTable(
  "screen_observations",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    operatorRunId: uuid("operator_run_id").references(() => operatorRuns.id, {
      onDelete: "cascade",
    }),
    screenshotHash: varchar("screenshot_hash", { length: 128 }).notNull(),
    elementsJson: jsonb("elements_json").notNull().default(sql`'[]'::jsonb`),
    activeApp: varchar("active_app", { length: 255 }),
    activeWindow: varchar("active_window", { length: 500 }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    runIdx: index("screen_observations_run_idx").on(table.operatorRunId),
    hashIdx: index("screen_observations_hash_idx").on(table.screenshotHash),
  }),
);

export const operatorSteps = pgTable(
  "operator_steps",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    operatorRunId: uuid("operator_run_id")
      .notNull()
      .references(() => operatorRuns.id, { onDelete: "cascade" }),
    stepIndex: integer("step_index").notNull(),
    screenObservationId: uuid("screen_observation_id").references(() => screenObservations.id, {
      onDelete: "set null",
    }),
    proposedAction: jsonb("proposed_action").notNull().default(sql`'{}'::jsonb`),
    executedAction: jsonb("executed_action").notNull().default(sql`'{}'::jsonb`),
    result: jsonb("result").notNull().default(sql`'{}'::jsonb`),
    requiresApproval: boolean("requires_approval").notNull().default(false),
    approvedByUser: boolean("approved_by_user").notNull().default(false),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    runStepIdx: uniqueIndex("operator_steps_run_step_uidx").on(table.operatorRunId, table.stepIndex),
  }),
);

export const inputActions = pgTable(
  "input_actions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    operatorStepId: uuid("operator_step_id")
      .notNull()
      .references(() => operatorSteps.id, { onDelete: "cascade" }),
    actionType: varchar("action_type", { length: 64 }).notNull(),
    targetBbox: jsonb("target_bbox").notNull().default(sql`'{}'::jsonb`),
    textRedacted: boolean("text_redacted").notNull().default(false),
    status: varchar("status", { length: 40 }).notNull().default("pending"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    stepIdx: index("input_actions_step_idx").on(table.operatorStepId),
  }),
);

export const blobObjects = pgTable(
  "blob_objects",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    contentSha256: varchar("content_sha256", { length: 64 }).notNull(),
    scope: varchar("scope", { length: 80 }).notNull(),
    addressKey: varchar("address_key", { length: 128 }).notNull(),
    contentType: varchar("content_type", { length: 255 }).notNull(),
    compression: varchar("compression", { length: 32 }).notNull().default("identity"),
    rawSize: integer("raw_size").notNull().default(0),
    storedSize: integer("stored_size").notNull().default(0),
    storageKey: text("storage_key").notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    lastAccessedAt: timestamp("last_accessed_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    scopeHashIdx: uniqueIndex("blob_objects_scope_hash_uidx").on(table.scope, table.contentSha256),
    addressIdx: uniqueIndex("blob_objects_address_uidx").on(table.addressKey),
    storageKeyIdx: uniqueIndex("blob_objects_storage_key_uidx").on(table.storageKey),
    scopeIdx: index("blob_objects_scope_idx").on(table.scope),
  }),
);

export const blobReferences = pgTable(
  "blob_references",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    ownerType: varchar("owner_type", { length: 64 }).notNull(),
    ownerId: varchar("owner_id", { length: 120 }).notNull(),
    slot: varchar("slot", { length: 80 }).notNull(),
    blobId: uuid("blob_id")
      .notNull()
      .references(() => blobObjects.id, { onDelete: "cascade" }),
    expiresAt: timestamp("expires_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
  },
  (table) => ({
    ownerSlotIdx: uniqueIndex("blob_references_owner_slot_blob_uidx").on(
      table.ownerType,
      table.ownerId,
      table.slot,
      table.blobId,
    ),
    blobIdx: index("blob_references_blob_idx").on(table.blobId),
    ownerIdx: index("blob_references_owner_idx").on(table.ownerType, table.ownerId),
    expiresIdx: index("blob_references_expires_idx").on(table.expiresAt),
  }),
);

export const tasks = pgTable(
  "tasks",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    targetDeviceId: uuid("target_device_id")
      .notNull()
      .references(() => devices.id, { onDelete: "cascade" }),
    title: varchar("title", { length: 200 }).notNull(),
    payload: jsonb("payload").notNull(),
    payloadBlobId: uuid("payload_blob_id").references(() => blobObjects.id, { onDelete: "set null" }),
    requestedCapabilities: jsonb("requested_capabilities").notNull().default(sql`'[]'::jsonb`),
    preferredAiProvider: aiProviderEnum("preferred_ai_provider"),
    runtimeConnectionId: uuid("runtime_connection_id").references(() => runtimeConnections.id, {
      onDelete: "set null",
    }),
    dispatchLeaseId: varchar("dispatch_lease_id", { length: 120 }),
    dispatchLeaseIssuedAt: timestamp("dispatch_lease_issued_at", { withTimezone: true }),
    dispatchLeaseExpiresAt: timestamp("dispatch_lease_expires_at", { withTimezone: true }),
    dispatchAckAt: timestamp("dispatch_ack_at", { withTimezone: true }),
    dispatchAttemptCount: integer("dispatch_attempt_count").notNull().default(0),
    idempotencyKey: varchar("idempotency_key", { length: 160 }),
    idempotencyFingerprint: varchar("idempotency_fingerprint", { length: 64 }),
    status: taskStatusEnum("status").notNull().default("queued"),
    queuePosition: integer("queue_position").notNull().default(0),
    summary: text("summary"),
    error: text("error"),
    approvalRequest: jsonb("approval_request"),
    approvalRequestBlobId: uuid("approval_request_blob_id").references(() => blobObjects.id, { onDelete: "set null" }),
    result: jsonb("result"),
    resultBlobId: uuid("result_blob_id").references(() => blobObjects.id, { onDelete: "set null" }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    canceledAt: timestamp("canceled_at", { withTimezone: true }),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("tasks_user_idx").on(table.userId),
    targetDeviceIdx: index("tasks_target_device_idx").on(table.targetDeviceId),
    statusIdx: index("tasks_status_idx").on(table.status),
    idempotencyIdx: uniqueIndex("tasks_user_idempotency_key_uidx").on(table.userId, table.idempotencyKey),
  }),
);

export const taskEvents = pgTable(
  "task_events",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    taskId: uuid("task_id")
      .notNull()
      .references(() => tasks.id, { onDelete: "cascade" }),
    status: taskStatusEnum("status").notNull(),
    message: text("message"),
    payload: jsonb("payload"),
    payloadBlobId: uuid("payload_blob_id").references(() => blobObjects.id, { onDelete: "set null" }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    taskIdx: index("task_events_task_idx").on(table.taskId),
    taskCreatedIdx: index("task_events_task_created_idx").on(table.taskId, table.createdAt),
  }),
);

export const realtimeEvents = pgTable(
  "realtime_events",
  {
    id: serial("id").primaryKey(),
    topic: varchar("topic", { length: 120 }).notNull(),
    userId: uuid("user_id").references(() => users.id, { onDelete: "cascade" }),
    deviceId: uuid("device_id").references(() => devices.id, { onDelete: "cascade" }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "cascade" }),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    payloadBlobId: uuid("payload_blob_id").references(() => blobObjects.id, { onDelete: "set null" }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("realtime_events_user_idx").on(table.userId, table.id),
    deviceIdx: index("realtime_events_device_idx").on(table.deviceId, table.id),
    taskIdx: index("realtime_events_task_idx").on(table.taskId, table.id),
  }),
);

export const artifacts = pgTable(
  "artifacts",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    taskId: uuid("task_id")
      .notNull()
      .references(() => tasks.id, { onDelete: "cascade" }),
    kind: artifactKindEnum("kind").notNull(),
    name: varchar("name", { length: 255 }).notNull(),
    contentType: varchar("content_type", { length: 255 }).notNull(),
    storageKey: text("storage_key"),
    textContent: text("text_content"),
    payload: jsonb("payload"),
    bodyBlobId: uuid("body_blob_id").references(() => blobObjects.id, { onDelete: "set null" }),
    contentHash: varchar("content_hash", { length: 64 }),
    byteLength: integer("byte_length"),
    contentEncoding: varchar("content_encoding", { length: 32 }),
    downloadable: boolean("downloadable").notNull().default(false),
    viewerHint: varchar("viewer_hint", { length: 32 }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    taskIdx: index("artifacts_task_idx").on(table.taskId),
  }),
);

export const subscriptions = pgTable(
  "subscriptions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" })
      .unique(),
    planCode: varchar("plan_code", { length: 64 }).notNull().default("free"),
    status: subscriptionStatusEnum("status").notNull().default("free"),
    billingProvider: varchar("billing_provider", { length: 32 }).notNull().default("iyzico"),
    providerCustomerReferenceCode: varchar("provider_customer_reference_code", { length: 160 }),
    providerSubscriptionReferenceCode: varchar("provider_subscription_reference_code", { length: 160 }),
    providerPricingPlanReferenceCode: varchar("provider_pricing_plan_reference_code", { length: 160 }),
    taskLimitMonthly: integer("task_limit_monthly").notNull().default(100),
    aiCreditsMonthly: integer("ai_credits_monthly").notNull().default(0),
    currentPeriodStartedAt: timestamp("current_period_started_at", { withTimezone: true }),
    periodEndsAt: timestamp("period_ends_at", { withTimezone: true }),
    trialEndsAt: timestamp("trial_ends_at", { withTimezone: true }),
    canceledAt: timestamp("canceled_at", { withTimezone: true }),
    cancelAtPeriodEnd: boolean("cancel_at_period_end").notNull().default(false),
    // Deferred downgrade: the lower plan the user already bought, applied when
    // the current paid period ends (Claude-style — paid days are never lost).
    pendingPlanCode: varchar("pending_plan_code", { length: 64 }),
    pendingPlanEffectiveAt: timestamp("pending_plan_effective_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("subscriptions_user_idx").on(table.userId),
  }),
);

export const billingProfiles = pgTable(
  "billing_profiles",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" })
      .unique(),
    fullName: varchar("full_name", { length: 160 }).notNull(),
    email: varchar("email", { length: 320 }).notNull(),
    phone: varchar("phone", { length: 32 }).notNull(),
    identityNumber: varchar("identity_number", { length: 32 }).notNull(),
    addressLine1: varchar("address_line_1", { length: 255 }).notNull(),
    city: varchar("city", { length: 120 }).notNull(),
    country: varchar("country", { length: 120 }).notNull(),
    zipCode: varchar("zip_code", { length: 32 }).notNull(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("billing_profiles_user_idx").on(table.userId),
  }),
);

export const billingPlanMappings = pgTable(
  "billing_plan_mappings",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    provider: varchar("provider", { length: 32 }).notNull().default("iyzico"),
    planCode: varchar("plan_code", { length: 64 }).notNull(),
    productReferenceCode: varchar("product_reference_code", { length: 160 }).notNull(),
    pricingPlanReferenceCode: varchar("pricing_plan_reference_code", { length: 160 }).notNull(),
    productName: varchar("product_name", { length: 160 }).notNull(),
    pricingPlanName: varchar("pricing_plan_name", { length: 160 }).notNull(),
    currencyCode: varchar("currency_code", { length: 8 }).notNull(),
    priceMinor: integer("price_minor").notNull(),
    billingPeriod: varchar("billing_period", { length: 16 }).notNull().default("monthly"),
    syncedAt: timestamp("synced_at", { withTimezone: true }).notNull().defaultNow(),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    providerIdx: index("billing_plan_mappings_provider_idx").on(table.provider),
    providerPlanCodeUniqueIdx: uniqueIndex("billing_plan_mappings_provider_plan_code_unique").on(
      table.provider,
      table.planCode,
    ),
  }),
);

export const billingCheckoutSessions = pgTable(
  "billing_checkout_sessions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    referenceId: varchar("reference_id", { length: 160 }).notNull().unique(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    planCode: varchar("plan_code", { length: 64 }).notNull(),
    provider: varchar("provider", { length: 32 }).notNull().default("iyzico"),
    mode: varchar("mode", { length: 32 }).notNull().default("subscription"),
    providerToken: varchar("provider_token", { length: 255 }),
    providerPaymentId: varchar("provider_payment_id", { length: 255 }),
    providerSubscriptionReferenceCode: varchar("provider_subscription_reference_code", { length: 160 }),
    providerCustomerReferenceCode: varchar("provider_customer_reference_code", { length: 160 }),
    providerPricingPlanReferenceCode: varchar("provider_pricing_plan_reference_code", { length: 160 }),
    idempotencyKey: varchar("idempotency_key", { length: 160 }),
    idempotencyFingerprint: varchar("idempotency_fingerprint", { length: 64 }),
    status: varchar("status", { length: 64 }).notNull().default("pending"),
    launchUrl: text("launch_url"),
    paymentPageUrl: text("payment_page_url"),
    callbackUrl: text("callback_url"),
    successUrl: text("success_url"),
    cancelUrl: text("cancel_url"),
    rawLastPayload: jsonb("raw_last_payload").notNull().default(sql`'{}'::jsonb`),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("billing_checkout_sessions_user_idx").on(table.userId),
    providerTokenIdx: index("billing_checkout_sessions_provider_token_idx").on(table.providerToken),
    providerSubscriptionIdx: index("billing_checkout_sessions_provider_subscription_idx").on(
      table.providerSubscriptionReferenceCode,
    ),
    idempotencyIdx: uniqueIndex("billing_checkout_user_idempotency_key_uidx").on(table.userId, table.idempotencyKey),
  }),
);

export const billingWebhookEvents = pgTable(
  "billing_webhook_events",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    eventKey: varchar("event_key", { length: 255 }).notNull().unique(),
    provider: varchar("provider", { length: 32 }).notNull().default("iyzico"),
    eventType: varchar("event_type", { length: 120 }).notNull(),
    userId: uuid("user_id").references(() => users.id, { onDelete: "set null" }),
    checkoutReferenceId: varchar("checkout_reference_id", { length: 160 }),
    providerSubscriptionReferenceCode: varchar("provider_subscription_reference_code", { length: 160 }),
    providerCustomerReferenceCode: varchar("provider_customer_reference_code", { length: 160 }),
    status: varchar("status", { length: 64 }),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    receivedAt: timestamp("received_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    providerIdx: index("billing_webhook_events_provider_idx").on(table.provider),
    userIdx: index("billing_webhook_events_user_idx").on(table.userId),
  }),
);

export const billingStoreTransactions = pgTable(
  "billing_store_transactions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id").references(() => users.id, { onDelete: "set null" }),
    provider: varchar("provider", { length: 32 }).notNull(),
    planCode: varchar("plan_code", { length: 64 }),
    productId: varchar("product_id", { length: 160 }),
    purchaseToken: varchar("purchase_token", { length: 255 }),
    originalTransactionId: varchar("original_transaction_id", { length: 255 }),
    transactionId: varchar("transaction_id", { length: 255 }),
    orderId: varchar("order_id", { length: 255 }),
    linkedPurchaseToken: varchar("linked_purchase_token", { length: 255 }),
    environment: varchar("environment", { length: 32 }),
    appAccountToken: uuid("app_account_token"),
    status: varchar("status", { length: 64 }).notNull(),
    rawPayloadHash: varchar("raw_payload_hash", { length: 64 }).notNull(),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    verifiedAt: timestamp("verified_at", { withTimezone: true }).notNull().defaultNow(),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }).notNull().defaultNow(),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    providerIdx: index("billing_store_transactions_provider_idx").on(table.provider),
    userIdx: index("billing_store_transactions_user_idx").on(table.userId),
    providerTransactionIdx: uniqueIndex("billing_store_transactions_provider_txn_uidx").on(
      table.provider,
      table.transactionId,
    ),
    providerPurchaseTokenIdx: uniqueIndex("billing_store_transactions_provider_purchase_uidx").on(
      table.provider,
      table.purchaseToken,
    ),
    providerOriginalTxnIdx: index("billing_store_transactions_provider_original_idx").on(
      table.provider,
      table.originalTransactionId,
    ),
    providerOriginalTxnUniqueIdx: uniqueIndex("billing_store_transactions_provider_original_uidx").on(
      table.provider,
      table.originalTransactionId,
    ),
  }),
);

export const billingEntitlementEvents = pgTable(
  "billing_entitlement_events",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    storeTransactionId: uuid("store_transaction_id").references(() => billingStoreTransactions.id, {
      onDelete: "set null",
    }),
    sourceProvider: varchar("source_provider", { length: 32 }).notNull(),
    planCode: varchar("plan_code", { length: 64 }).notNull(),
    eventType: varchar("event_type", { length: 64 }).notNull(),
    status: varchar("status", { length: 64 }).notNull(),
    sourceReferenceCode: varchar("source_reference_code", { length: 255 }),
    eventFingerprint: varchar("event_fingerprint", { length: 64 }).notNull(),
    effectivePeriodStartedAt: timestamp("effective_period_started_at", { withTimezone: true }),
    effectivePeriodEndsAt: timestamp("effective_period_ends_at", { withTimezone: true }),
    creditGrantAmount: integer("credit_grant_amount").notNull().default(0),
    creditDelta: integer("credit_delta").notNull().default(0),
    revokeFutureEntitlement: boolean("revoke_future_entitlement").notNull().default(false),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("billing_entitlement_events_user_idx").on(table.userId),
    providerIdx: index("billing_entitlement_events_provider_idx").on(table.sourceProvider),
    fingerprintIdx: uniqueIndex("billing_entitlement_events_fingerprint_uidx").on(table.eventFingerprint),
  }),
);

export const billingCreditLedger = pgTable(
  "billing_credit_ledger",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    entitlementEventId: uuid("entitlement_event_id").references(() => billingEntitlementEvents.id, {
      onDelete: "set null",
    }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    aiProviderInvocationId: uuid("ai_provider_invocation_id").references(() => aiProviderInvocations.id, {
      onDelete: "set null",
    }),
    reason: varchar("reason", { length: 80 }).notNull(),
    deltaCredits: integer("delta_credits").notNull(),
    balanceAfter: integer("balance_after").notNull(),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("billing_credit_ledger_user_idx").on(table.userId, table.createdAt),
    entitlementIdx: index("billing_credit_ledger_entitlement_idx").on(table.entitlementEventId),
    invocationReasonIdx: uniqueIndex("billing_credit_ledger_invocation_reason_uidx").on(
      table.aiProviderInvocationId,
      table.reason,
    ),
  }),
);

export const aiProviderCredentials = pgTable(
  "ai_provider_credentials",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: aiProviderEnum("provider").notNull(),
    label: varchar("label", { length: 120 }),
    encryptedPayload: text("encrypted_payload").notNull(),
    defaultModel: varchar("default_model", { length: 160 }),
    baseUrl: text("base_url"),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("ai_provider_credentials_user_idx").on(table.userId),
    providerIdx: index("ai_provider_credentials_provider_idx").on(table.provider),
  }),
);

export const aiProviderInvocations = pgTable(
  "ai_provider_invocations",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    provider: aiProviderEnum("provider").notNull(),
    model: varchar("model", { length: 160 }).notNull(),
    workload: varchar("workload", { length: 80 }).notNull(),
    route: varchar("route", { length: 80 }).notNull(),
    status: aiInvocationStatusEnum("status").notNull(),
    promptTokens: integer("prompt_tokens").notNull().default(0),
    completionTokens: integer("completion_tokens").notNull().default(0),
    totalTokens: integer("total_tokens").notNull().default(0),
    latencyMs: integer("latency_ms"),
    fallbackFromProvider: aiProviderEnum("fallback_from_provider"),
    fallbackFromModel: varchar("fallback_from_model", { length: 160 }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("ai_provider_invocations_user_idx").on(table.userId),
    taskIdx: index("ai_provider_invocations_task_idx").on(table.taskId),
    providerIdx: index("ai_provider_invocations_provider_idx").on(table.provider),
  }),
);

export const learningEvents = pgTable(
  "learning_events",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    accountId: uuid("account_id"),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    type: varchar("type", { length: 64 }).notNull(),
    key: varchar("key", { length: 120 }).notNull(),
    value: text("value").notNull(),
    confidence: integer("confidence").notNull().default(50),
    scope: varchar("scope", { length: 32 }).notNull().default("user"),
    source: varchar("source", { length: 64 }).notNull().default("interaction"),
    privacyLevel: varchar("privacy_level", { length: 32 }).notNull().default("safe"),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    expiresAt: timestamp("expires_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("learning_events_user_idx").on(table.userId),
    accountIdx: index("learning_events_account_idx").on(table.accountId),
    taskIdx: index("learning_events_task_idx").on(table.taskId),
    lookupIdx: index("learning_events_lookup_idx").on(table.userId, table.scope, table.type, table.key),
    expiresIdx: index("learning_events_expires_idx").on(table.expiresAt),
    // MÜKERRER ÖĞRENME KAYDINA KARŞI YAPISAL KISIT.
    //
    // Bir sohbet turu birden fazla kez işlenebiliyor (sağlayıcı fallback'i işi
    // ikinci kuyruğa alıyor). Yazım idempotent olmadığı için aynı olgu korpusa
    // iki-üç kez giriyordu; ölçüm (2026-08-13, üretim): task kapsamlı 1426
    // kaydın 494'ü mükerrer — %35. Bu tablo eğitim korpusunun KENDİSİ, yani
    // mükerrer satır aynı olguyu birden çok kez saydırıp modeli yanıltır.
    //
    // Kısmi: `task_id` NULL olan kayıtlar (görev bağlamı olmayan sinyaller)
    // kapsam dışı — Postgres'te NULL'lar zaten birbirinden farklı sayılır.
    taskKeyUidx: uniqueIndex("learning_events_task_key_uidx")
      .on(table.taskId, table.type, table.key)
      .where(sql`${table.taskId} is not null`),
  }),
);

export const datasetManifests = pgTable(
  "dataset_manifests",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    ownerUserId: uuid("owner_user_id").references(() => users.id, { onDelete: "set null" }),
    scope: brainScopeEnum("scope").notNull().default("user"),
    name: varchar("name", { length: 160 }).notNull(),
    source: datasetSourceEnum("source").notNull(),
    format: datasetFormatEnum("format").notNull(),
    status: datasetStatusEnum("status").notNull().default("draft"),
    description: text("description"),
    locator: text("locator"),
    languageTags: jsonb("language_tags").notNull().default(sql`'[]'::jsonb`),
    recordCount: integer("record_count").notNull().default(0),
    tokenEstimate: integer("token_estimate").notNull().default(0),
    lineage: varchar("lineage", { length: 80 }).notNull().default("legacy"),
    privacyReport: jsonb("privacy_report").notNull().default(sql`'{}'::jsonb`),
    qualityReport: jsonb("quality_report").notNull().default(sql`'{}'::jsonb`),
    replayRatio: integer("replay_ratio").notNull().default(0),
    candidateStatus: varchar("candidate_status", { length: 32 }).notNull().default("not_candidate"),
    sourceWindowStart: timestamp("source_window_start", { withTimezone: true }),
    sourceWindowEnd: timestamp("source_window_end", { withTimezone: true }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    ownerIdx: index("dataset_manifests_owner_idx").on(table.ownerUserId),
    scopeIdx: index("dataset_manifests_scope_idx").on(table.scope),
    statusIdx: index("dataset_manifests_status_idx").on(table.status),
    lineageIdx: index("dataset_manifests_lineage_idx").on(table.lineage),
    candidateIdx: index("dataset_manifests_candidate_status_idx").on(table.candidateStatus),
  }),
);

export const continuousLearningRuns = pgTable(
  "continuous_learning_runs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    ownerUserId: uuid("owner_user_id").references(() => users.id, { onDelete: "set null" }),
    scope: brainScopeEnum("scope").notNull().default("shared"),
    status: varchar("status", { length: 32 }).notNull().default("draft"),
    windowStart: timestamp("window_start", { withTimezone: true }).notNull(),
    windowEnd: timestamp("window_end", { withTimezone: true }).notNull(),
    datasetManifestId: uuid("dataset_manifest_id").references(() => datasetManifests.id, { onDelete: "set null" }),
    sourceEventCount: integer("source_event_count").notNull().default(0),
    acceptedEventCount: integer("accepted_event_count").notNull().default(0),
    rejectedEventCount: integer("rejected_event_count").notNull().default(0),
    dedupedEventCount: integer("deduped_event_count").notNull().default(0),
    replayRecordCount: integer("replay_record_count").notNull().default(0),
    trainRecordCount: integer("train_record_count").notNull().default(0),
    validationRecordCount: integer("validation_record_count").notNull().default(0),
    privacyReport: jsonb("privacy_report").notNull().default(sql`'{}'::jsonb`),
    qualityReport: jsonb("quality_report").notNull().default(sql`'{}'::jsonb`),
    replayReport: jsonb("replay_report").notNull().default(sql`'{}'::jsonb`),
    promotionReport: jsonb("promotion_report").notNull().default(sql`'{}'::jsonb`),
    config: jsonb("config").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    ownerIdx: index("continuous_learning_runs_owner_idx").on(table.ownerUserId),
    scopeStatusIdx: index("continuous_learning_runs_scope_status_idx").on(table.scope, table.status),
    windowIdx: index("continuous_learning_runs_window_idx").on(table.windowStart, table.windowEnd),
    datasetIdx: index("continuous_learning_runs_dataset_idx").on(table.datasetManifestId),
  }),
);

export const trainingJobs = pgTable(
  "training_jobs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    ownerUserId: uuid("owner_user_id").references(() => users.id, { onDelete: "set null" }),
    scope: brainScopeEnum("scope").notNull().default("user"),
    name: varchar("name", { length: 160 }).notNull(),
    kind: trainingJobKindEnum("kind").notNull(),
    status: trainingJobStatusEnum("status").notNull().default("queued"),
    baseModel: varchar("base_model", { length: 160 }).notNull(),
    datasetManifestId: uuid("dataset_manifest_id").references(() => datasetManifests.id, { onDelete: "set null" }),
    config: jsonb("config").notNull().default(sql`'{}'::jsonb`),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    metrics: jsonb("metrics").notNull().default(sql`'{}'::jsonb`),
    error: text("error"),
    startedAt: timestamp("started_at", { withTimezone: true }),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    ownerIdx: index("training_jobs_owner_idx").on(table.ownerUserId),
    scopeIdx: index("training_jobs_scope_idx").on(table.scope),
    statusIdx: index("training_jobs_status_idx").on(table.status),
    datasetIdx: index("training_jobs_dataset_idx").on(table.datasetManifestId),
    activeMemoryJobIdx: uniqueIndex("training_jobs_active_memory_user_kind_uidx")
      .on(table.ownerUserId, table.kind)
      .where(sql`${table.ownerUserId} is not null and ${table.kind} in ('memory_extraction', 'memory_consolidation', 'memory_index', 'memory_decay') and ${table.status} in ('queued', 'running')`),
  }),
);

export const modelArtifacts = pgTable(
  "model_artifacts",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    ownerUserId: uuid("owner_user_id").references(() => users.id, { onDelete: "set null" }),
    scope: brainScopeEnum("scope").notNull().default("user"),
    trainingJobId: uuid("training_job_id").references(() => trainingJobs.id, { onDelete: "set null" }),
    name: varchar("name", { length: 160 }).notNull(),
    provider: varchar("provider", { length: 80 }).notNull().default("manual"),
    baseModel: varchar("base_model", { length: 160 }).notNull(),
    adapterKind: varchar("adapter_kind", { length: 80 }).notNull().default("lora"),
    status: modelArtifactStatusEnum("status").notNull().default("draft"),
    storageUri: text("storage_uri"),
    checksum: varchar("checksum", { length: 128 }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    ownerIdx: index("model_artifacts_owner_idx").on(table.ownerUserId),
    scopeIdx: index("model_artifacts_scope_idx").on(table.scope),
    statusIdx: index("model_artifacts_status_idx").on(table.status),
    trainingJobIdx: index("model_artifacts_training_job_idx").on(table.trainingJobId),
  }),
);

export const knowledgeDocuments = pgTable(
  "knowledge_documents",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    ownerUserId: uuid("owner_user_id").references(() => users.id, { onDelete: "set null" }),
    scope: brainScopeEnum("scope").notNull().default("user"),
    title: varchar("title", { length: 200 }).notNull(),
    sourceType: knowledgeSourceTypeEnum("source_type").notNull(),
    status: knowledgeDocumentStatusEnum("status").notNull().default("processing"),
    sourceUri: text("source_uri"),
    contentHash: varchar("content_hash", { length: 64 }).notNull(),
    summary: text("summary"),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    ownerIdx: index("knowledge_documents_owner_idx").on(table.ownerUserId),
    scopeIdx: index("knowledge_documents_scope_idx").on(table.scope),
    statusIdx: index("knowledge_documents_status_idx").on(table.status),
    hashIdx: uniqueIndex("knowledge_documents_content_hash_uidx").on(table.scope, table.ownerUserId, table.contentHash),
  }),
);

export const knowledgeChunks = pgTable(
  "knowledge_chunks",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    documentId: uuid("document_id")
      .notNull()
      .references(() => knowledgeDocuments.id, { onDelete: "cascade" }),
    ownerUserId: uuid("owner_user_id").references(() => users.id, { onDelete: "set null" }),
    scope: brainScopeEnum("scope").notNull().default("user"),
    ordinal: integer("ordinal").notNull(),
    content: text("content").notNull(),
    tokenEstimate: integer("token_estimate").notNull().default(0),
    embeddingModel: varchar("embedding_model", { length: 160 }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    documentIdx: index("knowledge_chunks_document_idx").on(table.documentId),
    ownerIdx: index("knowledge_chunks_owner_idx").on(table.ownerUserId),
    scopeIdx: index("knowledge_chunks_scope_idx").on(table.scope),
    orderIdx: uniqueIndex("knowledge_chunks_document_ordinal_uidx").on(table.documentId, table.ordinal),
  }),
);

export const brainMemoryEpisodes = pgTable(
  "brain_memory_episodes",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    accountId: uuid("account_id"),
    scope: brainScopeEnum("scope").notNull().default("user"),
    sourceSessionId: uuid("source_session_id"),
    sourceTaskId: uuid("source_task_id").references(() => tasks.id, { onDelete: "set null" }),
    episodeType: varchar("episode_type", { length: 80 }).notNull(),
    summary: text("summary").notNull(),
    participants: jsonb("participants").notNull().default(sql`'[]'::jsonb`),
    startedAt: timestamp("started_at", { withTimezone: true }),
    endedAt: timestamp("ended_at", { withTimezone: true }),
    confidence: integer("confidence").notNull().default(50),
    importanceScore: integer("importance_score").notNull().default(50),
    isPinned: boolean("is_pinned").notNull().default(false),
    privacyLevel: varchar("privacy_level", { length: 32 }).notNull().default("safe"),
    lifecycleStatus: varchar("lifecycle_status", { length: 32 }).notNull().default("active"),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
    deletedReason: varchar("deleted_reason", { length: 240 }),
    supersedesEpisodeId: uuid("supersedes_episode_id"),
    embeddingModel: varchar("embedding_model", { length: 160 }),
    embeddingV2: vector384("embedding_v2"),
    embeddingV2Model: varchar("embedding_v2_model", { length: 96 }),
    staleAt: timestamp("stale_at", { withTimezone: true }),
    observedAt: timestamp("observed_at", { withTimezone: true }).notNull().defaultNow(),
    expiresAt: timestamp("expires_at", { withTimezone: true })
      .notNull()
      .default(sql`now() + interval '90 days'`),
    revision: integer("revision").notNull().default(1),
    sourceKind: varchar("source_kind", { length: 48 }).notNull().default("legacy"),
    sourceId: varchar("source_id", { length: 160 }),
    contentHash: varchar("content_hash", { length: 64 }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("brain_memory_episodes_user_idx").on(table.userId),
    scopeIdx: index("brain_memory_episodes_scope_idx").on(table.scope),
    taskIdx: index("brain_memory_episodes_task_idx").on(table.sourceTaskId),
    sessionIdx: index("brain_memory_episodes_session_idx").on(table.sourceSessionId),
    staleIdx: index("brain_memory_episodes_stale_idx").on(table.staleAt),
    pinnedIdx: index("brain_memory_episodes_pinned_idx").on(table.isPinned),
    lifecycleIdx: index("brain_memory_episodes_lifecycle_idx").on(table.lifecycleStatus),
    activeExpiryIdx: index("brain_memory_episodes_user_expiry_idx").on(
      table.userId,
      table.expiresAt,
    ),
  }),
);

export const brainMemoryFacts = pgTable(
  "brain_memory_facts",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    accountId: uuid("account_id"),
    scope: brainScopeEnum("scope").notNull().default("user"),
    factType: varchar("fact_type", { length: 48 }).notNull().default("semantic"),
    canonicalKey: varchar("canonical_key", { length: 160 }).notNull(),
    key: varchar("key", { length: 160 }).notNull(),
    value: text("value").notNull(),
    confidence: integer("confidence").notNull().default(50),
    importanceScore: integer("importance_score").notNull().default(50),
    isPinned: boolean("is_pinned").notNull().default(false),
    conflictStatus: varchar("conflict_status", { length: 32 }).notNull().default("active"),
    lifecycleStatus: varchar("lifecycle_status", { length: 32 }).notNull().default("active"),
    lastVerifiedAt: timestamp("last_verified_at", { withTimezone: true }),
    deletedAt: timestamp("deleted_at", { withTimezone: true }),
    deletedReason: varchar("deleted_reason", { length: 240 }),
    staleAt: timestamp("stale_at", { withTimezone: true }),
    supersedesFactId: uuid("supersedes_fact_id"),
    validFrom: timestamp("valid_from", { withTimezone: true }).notNull().defaultNow(),
    validTo: timestamp("valid_to", { withTimezone: true }),
    observedAt: timestamp("observed_at", { withTimezone: true }).notNull().defaultNow(),
    revision: integer("revision").notNull().default(1),
    sourceKind: varchar("source_kind", { length: 48 }).notNull().default("legacy"),
    sourceId: varchar("source_id", { length: 160 }),
    contentHash: varchar("content_hash", { length: 64 }),
    embeddingModel: varchar("embedding_model", { length: 160 }),
    embeddingV2: vector384("embedding_v2"),
    embeddingV2Model: varchar("embedding_v2_model", { length: 96 }),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("brain_memory_facts_user_idx").on(table.userId),
    scopeIdx: index("brain_memory_facts_scope_idx").on(table.scope),
    canonicalIdx: index("brain_memory_facts_canonical_idx").on(table.userId, table.canonicalKey),
    singleValueActiveIdx: uniqueIndex("brain_memory_facts_single_value_active_uidx")
      .on(table.userId, table.canonicalKey, table.factType)
      .where(sql`${table.conflictStatus} = 'active' and ${table.lifecycleStatus} = 'active' and ${table.deletedAt} is null and ${table.canonicalKey} in ('name', 'preferred_name', 'preferred_language', 'preferred_tone', 'response_style_preference', 'timezone', 'job_title', 'company', 'location', 'project', 'active_project', 'primary_repo', 'working_boundary', 'implementation_boundary')`),
    conflictIdx: index("brain_memory_facts_conflict_idx").on(table.conflictStatus),
    staleIdx: index("brain_memory_facts_stale_idx").on(table.staleAt),
    pinnedIdx: index("brain_memory_facts_pinned_idx").on(table.isPinned),
    lifecycleIdx: index("brain_memory_facts_lifecycle_idx").on(table.lifecycleStatus),
    temporalIdx: index("brain_memory_facts_user_temporal_idx").on(
      table.userId,
      table.canonicalKey,
      table.validFrom,
    ),
  }),
);

export const cognitiveMemoryRevisions = pgTable("cognitive_memory_revisions", {
  userId: uuid("user_id")
    .primaryKey()
    .references(() => users.id, { onDelete: "cascade" }),
  revision: integer("revision").notNull().default(0),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const cognitiveMutationOutbox = pgTable(
  "cognitive_mutation_outbox",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    sessionId: uuid("session_id"),
    revision: integer("revision").notNull(),
    eventType: varchar("event_type", { length: 64 }).notNull(),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    status: varchar("status", { length: 24 }).notNull().default("pending"),
    attempts: integer("attempts").notNull().default(0),
    availableAt: timestamp("available_at", { withTimezone: true }).notNull().defaultNow(),
    processedAt: timestamp("processed_at", { withTimezone: true }),
    lastErrorCode: varchar("last_error_code", { length: 96 }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    pendingIdx: index("cognitive_mutation_outbox_pending_idx").on(
      table.status,
      table.availableAt,
    ),
    userRevisionIdx: uniqueIndex("cognitive_mutation_outbox_user_revision_uidx").on(
      table.userId,
      table.revision,
    ),
  }),
);

export const tenantIntegrityQuarantine = pgTable(
  "tenant_integrity_quarantine",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    tableName: varchar("table_name", { length: 96 }).notNull(),
    rowIdHash: varchar("row_id_hash", { length: 64 }).notNull(),
    reasonCode: varchar("reason_code", { length: 96 }).notNull(),
    detectedAt: timestamp("detected_at", { withTimezone: true }).notNull().defaultNow(),
    resolvedAt: timestamp("resolved_at", { withTimezone: true }),
  },
  (table) => ({
    unresolvedIdx: index("tenant_integrity_quarantine_unresolved_idx").on(
      table.tableName,
      table.resolvedAt,
    ),
  }),
);

export const brainMemoryLinks = pgTable(
  "brain_memory_links",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    sourceEpisodeId: uuid("source_episode_id").references(() => brainMemoryEpisodes.id, { onDelete: "cascade" }),
    sourceFactId: uuid("source_fact_id").references(() => brainMemoryFacts.id, { onDelete: "cascade" }),
    targetEpisodeId: uuid("target_episode_id").references(() => brainMemoryEpisodes.id, { onDelete: "cascade" }),
    targetFactId: uuid("target_fact_id").references(() => brainMemoryFacts.id, { onDelete: "cascade" }),
    linkType: varchar("link_type", { length: 64 }).notNull(),
    confidence: integer("confidence").notNull().default(50),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("brain_memory_links_user_idx").on(table.userId),
    linkTypeIdx: index("brain_memory_links_type_idx").on(table.linkType),
  }),
);

export const brainMemoryRuns = pgTable(
  "brain_memory_runs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id").references(() => users.id, { onDelete: "cascade" }),
    scope: brainScopeEnum("scope").notNull().default("user"),
    runKind: varchar("run_kind", { length: 64 }).notNull(),
    status: varchar("status", { length: 32 }).notNull().default("completed"),
    sourceTrainingJobId: uuid("source_training_job_id").references(() => trainingJobs.id, { onDelete: "set null" }),
    processedCount: integer("processed_count").notNull().default(0),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    startedAt: timestamp("started_at", { withTimezone: true }).notNull().defaultNow(),
    completedAt: timestamp("completed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("brain_memory_runs_user_idx").on(table.userId),
    kindIdx: index("brain_memory_runs_kind_idx").on(table.runKind),
    statusIdx: index("brain_memory_runs_status_idx").on(table.status),
    startedIdx: index("brain_memory_runs_started_idx").on(table.startedAt),
  }),
);

export const chatSessions = pgTable(
  "chat_sessions",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    targetDeviceId: uuid("target_device_id")
      .notNull()
      .references(() => devices.id, { onDelete: "cascade" }),
    source: chatSessionSourceEnum("source").notNull().default("mobile"),
    status: chatSessionStatusEnum("status").notNull().default("active"),
    title: varchar("title", { length: 200 }).notNull(),
    lastMessageAt: timestamp("last_message_at", { withTimezone: true }).notNull().defaultNow(),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("chat_sessions_user_idx").on(table.userId),
    ownerIdx: uniqueIndex("chat_sessions_id_user_uidx").on(table.id, table.userId),
    targetDeviceIdx: index("chat_sessions_target_device_idx").on(table.targetDeviceId),
    statusIdx: index("chat_sessions_status_idx").on(table.status),
    lastMessageIdx: index("chat_sessions_last_message_idx").on(table.lastMessageAt),
  }),
);

export const dialogueStates = pgTable(
  "dialogue_states",
  {
    sessionId: uuid("session_id")
      .primaryKey()
      .references(() => chatSessions.id, { onDelete: "cascade" }),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    revision: integer("revision").notNull().default(0),
    state: jsonb("state").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userUpdatedIdx: index("dialogue_states_user_updated_idx").on(table.userId, table.updatedAt),
  }),
);

export const proactiveTriggers = pgTable(
  "proactive_triggers",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    sessionId: uuid("session_id").references(() => chatSessions.id, {
      onDelete: "cascade",
    }),
    kind: varchar("kind", { length: 40 }).notNull().default("follow_up"),
    due: timestamp("due", { withTimezone: true }).notNull(),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    status: varchar("status", { length: 32 }).notNull().default("pending"),
    createdBy: varchar("created_by", { length: 32 }).notNull().default("model"),
    /** Stable identity of the *subject*, so an observer sweep cannot pile up
     * duplicates of the same suggestion. Unique only while unresolved. */
    dedupeKey: varchar("dedupe_key", { length: 160 }),
    firedAt: timestamp("fired_at", { withTimezone: true }),
    canceledAt: timestamp("canceled_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userDueIdx: index("proactive_triggers_user_due_idx").on(table.userId, table.due),
    sessionDueIdx: index("proactive_triggers_session_due_idx").on(table.sessionId, table.due),
    statusDueIdx: index("proactive_triggers_status_due_idx").on(table.status, table.due),
    kindStatusIdx: index("proactive_triggers_kind_status_idx").on(table.kind, table.status),
  }),
);

/**
 * One row per unit of work Elyan takes on while the user is asleep.
 *
 * `evidence` is not nullable by design: a job whose origin cannot be traced
 * back to something observable is the fabrication failure mode, not a feature.
 */
export const nightWatchJobs = pgTable(
  "night_watch_jobs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    nightDate: date("night_date").notNull(),
    deviceId: uuid("device_id").references(() => devices.id, { onDelete: "set null" }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    sessionId: uuid("session_id").references(() => chatSessions.id, {
      onDelete: "set null",
    }),
    title: varchar("title", { length: 200 }).notNull(),
    prompt: text("prompt").notNull(),
    capabilities: jsonb("capabilities").notNull().default(sql`'[]'::jsonb`),
    evidence: jsonb("evidence").notNull(),
    fingerprint: varchar("fingerprint", { length: 64 }).notNull(),
    status: varchar("status", { length: 32 }).notNull().default("planned"),
    statusReason: varchar("status_reason", { length: 120 }),
    resultSummary: text("result_summary"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    dispatchedAt: timestamp("dispatched_at", { withTimezone: true }),
    settledAt: timestamp("settled_at", { withTimezone: true }),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userNightFingerprintUniqueIdx: uniqueIndex(
      "night_watch_jobs_user_night_fingerprint_uidx",
    ).on(table.userId, table.nightDate, table.fingerprint),
    userNightIdx: index("night_watch_jobs_user_night_idx").on(
      table.userId,
      table.nightDate,
    ),
    statusIdx: index("night_watch_jobs_status_idx").on(table.status),
  }),
);

/** Proactive telemetry. See `drizzle/0050_proactive_events.sql`. */
export const proactiveEvents = pgTable(
  "proactive_events",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    triggerId: uuid("trigger_id").references(() => proactiveTriggers.id, {
      onDelete: "set null",
    }),
    event: varchar("event", { length: 32 }).notNull(),
    kind: varchar("kind", { length: 48 }).notNull(),
    source: varchar("source", { length: 32 }).notNull().default("system"),
    reason: varchar("reason", { length: 120 }),
    detail: jsonb("detail").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userCreatedIdx: index("proactive_events_user_created_idx").on(
      table.userId,
      table.createdAt,
    ),
    eventCreatedIdx: index("proactive_events_event_created_idx").on(
      table.event,
      table.createdAt,
    ),
    kindCreatedIdx: index("proactive_events_kind_created_idx").on(
      table.kind,
      table.createdAt,
    ),
  }),
);

export const userProactivePrefs = pgTable("user_proactive_prefs", {
  userId: uuid("user_id")
    .primaryKey()
    .references(() => users.id, { onDelete: "cascade" }),
  enabled: boolean("enabled").notNull().default(true),
  maxDaily: integer("max_daily").notNull().default(3),
  quietStartHour: integer("quiet_start_hour").notNull().default(22),
  quietEndHour: integer("quiet_end_hour").notNull().default(8),
  timezone: varchar("timezone", { length: 80 }).notNull().default("Europe/Istanbul"),
  mutedKinds: jsonb("muted_kinds").notNull().default(sql`'[]'::jsonb`),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const userConsents = pgTable(
  "user_consents",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    consentType: text("consent_type").notNull(),
    consentVersion: text("consent_version").notNull(),
    granted: boolean("granted").notNull(),
    grantedAt: timestamp("granted_at", { withTimezone: true }),
    revokedAt: timestamp("revoked_at", { withTimezone: true }),
    source: text("source"),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userTypeVersionIdx: uniqueIndex("user_consents_user_type_version_uidx").on(
      table.userId,
      table.consentType,
      table.consentVersion,
    ),
    userTypeIdx: index("user_consents_user_type_idx").on(table.userId, table.consentType),
  }),
);

export const sessionGoals = pgTable(
  "session_goals",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    sessionId: uuid("session_id").references(() => chatSessions.id, {
      onDelete: "cascade",
    }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    title: varchar("title", { length: 200 }).notNull(),
    description: text("description").notNull().default(""),
    status: sessionGoalStatusEnum("status").notNull().default("active"),
    currentStep: integer("current_step").notNull().default(0),
    maxSteps: integer("max_steps").notNull().default(20),
    progress: jsonb("progress").notNull().default(sql`'{}'::jsonb`),
    scheduleHint: sessionGoalScheduleHintEnum("schedule_hint"),
    dueAt: timestamp("due_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userStatusIdx: index("session_goals_user_status_idx").on(table.userId, table.status),
    sessionStatusIdx: index("session_goals_session_status_idx").on(table.sessionId, table.status),
    taskIdx: index("session_goals_task_idx").on(table.taskId),
    dueIdx: index("session_goals_due_idx").on(table.dueAt),
  }),
);

export const goalEvents = pgTable(
  "goal_events",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    goalId: uuid("goal_id")
      .notNull()
      .references(() => sessionGoals.id, { onDelete: "cascade" }),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    eventType: varchar("event_type", { length: 48 }).notNull(),
    fromState: varchar("from_state", { length: 32 }),
    toState: varchar("to_state", { length: 32 }).notNull(),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    goalCreatedIdx: index("goal_events_goal_created_idx").on(table.goalId, table.createdAt),
    goalUserCreatedIdx: index("goal_events_goal_user_created_idx").on(
      table.goalId,
      table.userId,
      table.createdAt,
    ),
    userCreatedIdx: index("goal_events_user_created_idx").on(table.userId, table.createdAt),
  }),
);

export const agentRuns = pgTable("agent_runs", {
  id: uuid("id").defaultRandom().primaryKey(),
  userId: uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  taskId: uuid("task_id").notNull().references(() => tasks.id, { onDelete: "cascade" }).unique(),
  sessionId: uuid("session_id").references(() => chatSessions.id, { onDelete: "set null" }),
  goalId: uuid("goal_id").references(() => sessionGoals.id, { onDelete: "set null" }),
  state: varchar("state", { length: 32 }).notNull().default("understanding"),
  revision: integer("revision").notNull().default(1),
  plan: jsonb("plan").notNull().default(sql`'{}'::jsonb`),
  maxSteps: integer("max_steps").notNull().default(8),
  maxToolCalls: integer("max_tool_calls").notNull().default(12),
  maxReplans: integer("max_replans").notNull().default(2),
  toolCallCount: integer("tool_call_count").notNull().default(0),
  replanCount: integer("replan_count").notNull().default(0),
  activeComputeMs: integer("active_compute_ms").notNull().default(0),
  activeComputeBudgetMs: integer("active_compute_budget_ms").notNull().default(120_000),
  leaseOwner: varchar("lease_owner", { length: 160 }),
  leaseExpiresAt: timestamp("lease_expires_at", { withTimezone: true }),
  waitingExpiresAt: timestamp("waiting_expires_at", { withTimezone: true }),
  terminalResult: jsonb("terminal_result"),
  failureCode: varchar("failure_code", { length: 96 }),
  shadow: boolean("shadow").notNull().default(false),
  startedAt: timestamp("started_at", { withTimezone: true }),
  completedAt: timestamp("completed_at", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => ({
  idUserUnique: uniqueIndex("agent_runs_id_user_uidx").on(table.id, table.userId),
  userStateIdx: index("agent_runs_user_state_idx").on(table.userId, table.state, table.updatedAt),
  leaseIdx: index("agent_runs_lease_idx").on(table.state, table.leaseExpiresAt),
}));

export const agentSteps = pgTable("agent_steps", {
  id: uuid("id").defaultRandom().primaryKey(),
  runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
  userId: uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  stepKey: varchar("step_key", { length: 80 }).notNull(),
  sequence: integer("sequence").notNull(),
  state: varchar("state", { length: 32 }).notNull().default("pending"),
  dependsOn: jsonb("depends_on").notNull().default(sql`'[]'::jsonb`),
  expectedOutcome: jsonb("expected_outcome").notNull().default(sql`'{}'::jsonb`),
  toolRequest: jsonb("tool_request").notNull().default(sql`'{}'::jsonb`),
  toolResult: jsonb("tool_result"),
  verification: jsonb("verification"),
  attempt: integer("attempt").notNull().default(0),
  maxAttempts: integer("max_attempts").notNull().default(3),
  idempotencyKey: varchar("idempotency_key", { length: 160 }).notNull().unique(),
  startedAt: timestamp("started_at", { withTimezone: true }),
  observedAt: timestamp("observed_at", { withTimezone: true }),
  verifiedAt: timestamp("verified_at", { withTimezone: true }),
  completedAt: timestamp("completed_at", { withTimezone: true }),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => ({
  runStepUnique: uniqueIndex("agent_steps_run_step_uidx").on(table.runId, table.stepKey),
  runStateIdx: index("agent_steps_run_state_idx").on(table.runId, table.state, table.sequence),
}));

export const agentEvidence = pgTable("agent_evidence", {
  id: uuid("id").defaultRandom().primaryKey(),
  runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
  stepId: uuid("step_id").notNull().references(() => agentSteps.id, { onDelete: "cascade" }),
  userId: uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  kind: varchar("kind", { length: 32 }).notNull(),
  sourceRef: varchar("source_ref", { length: 200 }),
  contentHash: varchar("content_hash", { length: 64 }),
  payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
  valid: boolean("valid").notNull().default(true),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => ({
  stepIdx: index("agent_evidence_step_idx").on(table.stepId, table.createdAt),
  runIdx: index("agent_evidence_run_idx").on(table.runId, table.createdAt),
}));

export const agentEvents = pgTable("agent_events", {
  id: uuid("id").defaultRandom().primaryKey(),
  runId: uuid("run_id").notNull().references(() => agentRuns.id, { onDelete: "cascade" }),
  stepId: uuid("step_id").references(() => agentSteps.id, { onDelete: "set null" }),
  userId: uuid("user_id").notNull().references(() => users.id, { onDelete: "cascade" }),
  revision: integer("revision").notNull(),
  eventType: varchar("event_type", { length: 64 }).notNull(),
  fromState: varchar("from_state", { length: 32 }),
  toState: varchar("to_state", { length: 32 }).notNull(),
  payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
}, (table) => ({
  runRevisionIdx: index("agent_events_run_revision_idx").on(table.runId, table.revision, table.createdAt),
  userCreatedIdx: index("agent_events_user_created_idx").on(table.userId, table.createdAt),
}));

export const chatMessages = pgTable(
  "chat_messages",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    sessionId: uuid("session_id")
      .notNull()
      .references(() => chatSessions.id, { onDelete: "cascade" }),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    role: chatMessageRoleEnum("role").notNull(),
    status: chatMessageStatusEnum("status").notNull().default("completed"),
    content: text("content").notNull().default(""),
    contentBlobId: uuid("content_blob_id").references(() => blobObjects.id, { onDelete: "set null" }),
    preview: varchar("preview", { length: 320 }),
    tokenCount: integer("token_count").notNull().default(0),
    error: text("error"),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    sessionIdx: index("chat_messages_session_idx").on(table.sessionId, table.createdAt),
    userIdx: index("chat_messages_user_idx").on(table.userId),
    taskIdx: index("chat_messages_task_idx").on(table.taskId),
    statusIdx: index("chat_messages_status_idx").on(table.status),
    orphanReconcileIdx: index("chat_messages_orphan_reconcile_idx")
      .on(table.createdAt)
      .where(
        sql`${table.role} = 'assistant' and ${table.taskId} is null and ${table.status} in ('queued', 'running')`,
      ),
  }),
);

export const turnMetrics = pgTable(
  "turn_metrics",
  {
    turnId: varchar("turn_id", { length: 160 }).primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    sessionId: uuid("session_id").references(() => chatSessions.id, {
      onDelete: "set null",
    }),
    workload: varchar("workload", { length: 80 }).notNull(),
    timings: jsonb("timings").notNull().default(sql`'{}'::jsonb`),
    quality: jsonb("quality").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userCreatedIdx: index("turn_metrics_user_created_idx").on(table.userId, table.createdAt),
    sessionCreatedIdx: index("turn_metrics_session_created_idx").on(table.sessionId, table.createdAt),
    workloadCreatedIdx: index("turn_metrics_workload_created_idx").on(table.workload, table.createdAt),
  }),
);

export const worldSignals = pgTable(
  "world_signals",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    deviceId: uuid("device_id")
      .notNull()
      .references(() => devices.id, { onDelete: "cascade" }),
    sessionId: uuid("session_id").references(() => chatSessions.id, {
      onDelete: "set null",
    }),
    clientRequestId: varchar("client_request_id", { length: 160 }).notNull(),
    signalId: varchar("signal_id", { length: 160 }).notNull(),
    source: varchar("source", { length: 32 }).notNull(),
    kind: varchar("kind", { length: 32 }).notNull(),
    summary: text("summary").notNull(),
    confidenceBps: integer("confidence_bps").notNull().default(0),
    facts: jsonb("facts").notNull().default(sql`'{}'::jsonb`),
    privacy: jsonb("privacy").notNull().default(sql`'{}'::jsonb`),
    renderHints: jsonb("render_hints").notNull().default(sql`'{}'::jsonb`),
    visibility: varchar("visibility", { length: 64 })
      .notNull()
      .default("assistant_internal_by_default"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull(),
    ingestedAt: timestamp("ingested_at", { withTimezone: true })
      .notNull()
      .defaultNow(),
  },
  (table) => ({
    userSignalUniqueIdx: uniqueIndex("world_signals_user_signal_uidx").on(
      table.userId,
      table.signalId,
    ),
    userDeviceCreatedIdx: index("world_signals_user_device_created_idx").on(
      table.userId,
      table.deviceId,
      table.createdAt,
    ),
    userSessionCreatedIdx: index("world_signals_user_session_created_idx").on(
      table.userId,
      table.sessionId,
      table.createdAt,
    ),
    kindIdx: index("world_signals_kind_idx").on(table.kind),
  }),
);

export const integrationConnections = pgTable(
  "integration_connections",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: connectionProviderEnum("provider").notNull(),
    appId: varchar("app_id", { length: 80 }),
    authType: integrationAuthTypeEnum("auth_type").notNull(),
    status: integrationConnectionStatusEnum("status").notNull().default("pending"),
    displayName: varchar("display_name", { length: 160 }),
    externalAccountId: varchar("external_account_id", { length: 160 }),
    scopes: jsonb("scopes").notNull().default(sql`'[]'::jsonb`),
    capabilities: jsonb("capabilities").notNull().default(sql`'[]'::jsonb`),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    lastSyncedAt: timestamp("last_synced_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("integration_connections_user_idx").on(table.userId),
    providerIdx: index("integration_connections_provider_idx").on(table.provider),
    userAppUniqueIdx: uniqueIndex("integration_connections_user_app_uidx").on(
      table.userId,
      table.appId,
    ),
  }),
);

export const integrationCredentials = pgTable(
  "integration_credentials",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    connectionId: uuid("connection_id")
      .notNull()
      .references(() => integrationConnections.id, { onDelete: "cascade" }),
    encryptedPayload: text("encrypted_payload").notNull(),
    expiresAt: timestamp("expires_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    connectionIdx: uniqueIndex("integration_credentials_connection_uidx").on(
      table.connectionId,
    ),
  }),
);

export const oauthStates = pgTable(
  "oauth_states",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: connectionProviderEnum("provider").notNull(),
    status: oauthStateStatusEnum("status").notNull().default("pending"),
    state: varchar("state", { length: 160 }).notNull().unique(),
    redirectUri: text("redirect_uri"),
    requestedScopes: jsonb("requested_scopes").notNull().default(sql`'[]'::jsonb`),
    codeVerifier: text("code_verifier"),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    expiresAt: timestamp("expires_at", { withTimezone: true }).notNull(),
    consumedAt: timestamp("consumed_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    stateIdx: index("oauth_states_state_idx").on(table.state),
    userIdx: index("oauth_states_user_idx").on(table.userId),
  }),
);

export const mcpServers = pgTable(
  "mcp_servers",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    integrationConnectionId: uuid("integration_connection_id").references(() => integrationConnections.id, {
      onDelete: "set null",
    }),
    name: varchar("name", { length: 160 }).notNull(),
    transport: mcpTransportEnum("transport").notNull(),
    authType: mcpAuthTypeEnum("auth_type").notNull().default("none"),
    status: mcpServerStatusEnum("status").notNull().default("configured"),
    baseUrl: text("base_url"),
    command: text("command"),
    args: jsonb("args").notNull().default(sql`'[]'::jsonb`),
    config: jsonb("config").notNull().default(sql`'{}'::jsonb`),
    capabilities: jsonb("capabilities").notNull().default(sql`'[]'::jsonb`),
    metadata: jsonb("metadata").notNull().default(sql`'{}'::jsonb`),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("mcp_servers_user_idx").on(table.userId),
    integrationIdx: index("mcp_servers_integration_idx").on(table.integrationConnectionId),
  }),
);

export const auditLogs = pgTable(
  "audit_logs",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id").references(() => users.id, { onDelete: "set null" }),
    actorType: auditActorTypeEnum("actor_type").notNull(),
    actorId: varchar("actor_id", { length: 160 }),
    action: varchar("action", { length: 160 }).notNull(),
    resourceType: varchar("resource_type", { length: 120 }).notNull(),
    resourceId: varchar("resource_id", { length: 160 }),
    status: auditStatusEnum("status").notNull(),
    ipAddress: varchar("ip_address", { length: 64 }),
    userAgent: text("user_agent"),
    requestId: varchar("request_id", { length: 160 }),
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("audit_logs_user_idx").on(table.userId),
    actorIdx: index("audit_logs_actor_idx").on(table.actorType, table.actorId),
    requestIdx: index("audit_logs_request_idx").on(table.requestId),
  }),
);

export const usageRecords = pgTable(
  "usage_records",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    identityId: uuid("identity_id").references(() => userIdentityHistory.id, {
      onDelete: "set null",
    }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    metric: varchar("metric", { length: 80 }).notNull(),
    quantity: integer("quantity").notNull().default(0),
    budgetUnits: integer("budget_units").notNull().default(0),
    documentUnits: integer("document_units").notNull().default(0),
    imageUnits: integer("image_units").notNull().default(0),
    toolUnits: integer("tool_units").notNull().default(0),
    qualityProfile: varchar("quality_profile", { length: 32 }),
    planSnapshot: jsonb("plan_snapshot").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("usage_records_user_idx").on(table.userId),
    identityIdx: index("usage_records_identity_idx").on(table.identityId),
    taskIdx: index("usage_records_task_idx").on(table.taskId),
    taskMetricUniqueIdx: uniqueIndex("usage_records_task_metric_uidx").on(table.taskId, table.metric),
  }),
);

export const quotaState = pgTable(
  "quota_state",
  {
    identityId: uuid("identity_id")
      .primaryKey()
      .references(() => userIdentityHistory.id, { onDelete: "cascade" }),
    dailyUsedUnits: integer("daily_used_units").notNull().default(0),
    weeklyUsedUnits: integer("weekly_used_units").notNull().default(0),
    dailyResetAt: timestamp("daily_reset_at", { withTimezone: true }).notNull(),
    weeklyResetAt: timestamp("weekly_reset_at", { withTimezone: true }).notNull(),
    documentUploadCount: integer("document_upload_count").notNull().default(0),
    imageUploadCount: integer("image_upload_count").notNull().default(0),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    dailyResetIdx: index("quota_state_daily_reset_idx").on(table.dailyResetAt),
    weeklyResetIdx: index("quota_state_weekly_reset_idx").on(table.weeklyResetAt),
  }),
);

export const usageWindows = pgTable(
  "usage_windows",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    identityId: uuid("identity_id")
      .notNull()
      .references(() => userIdentityHistory.id, { onDelete: "cascade" }),
    windowType: usageWindowTypeEnum("window_type").notNull(),
    windowStartedAt: timestamp("window_started_at", { withTimezone: true }).notNull(),
    windowEndsAt: timestamp("window_ends_at", { withTimezone: true }).notNull(),
    usedUnits: integer("used_units").notNull().default(0),
    documentUploadCount: integer("document_upload_count").notNull().default(0),
    imageUploadCount: integer("image_upload_count").notNull().default(0),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    identityWindowUniqueIdx: uniqueIndex("usage_windows_identity_window_uidx").on(
      table.identityId,
      table.windowType,
    ),
    identityIdx: index("usage_windows_identity_idx").on(table.identityId),
  }),
);

export const usersRelations = relations(users, ({ many, one }) => ({
  sessions: many(sessions),
  devices: many(devices),
  identity: one(userIdentityHistory, {
    fields: [users.identityId],
    references: [userIdentityHistory.id],
  }),
  avatar: one(userAvatars, {
    fields: [users.id],
    references: [userAvatars.userId],
  }),
  billingCheckouts: many(billingCheckoutSessions),
  billingProfile: one(billingProfiles, {
    fields: [users.id],
    references: [billingProfiles.userId],
  }),
  aiProviderCredentials: many(aiProviderCredentials),
  learningEvents: many(learningEvents),
  datasetManifests: many(datasetManifests),
  trainingJobs: many(trainingJobs),
  modelArtifacts: many(modelArtifacts),
  knowledgeDocuments: many(knowledgeDocuments),
  knowledgeChunks: many(knowledgeChunks),
  chatSessions: many(chatSessions),
  chatMessages: many(chatMessages),
  sessionGoals: many(sessionGoals),
  integrationConnections: many(integrationConnections),
  mcpServers: many(mcpServers),
  subscription: one(subscriptions, {
    fields: [users.id],
    references: [subscriptions.userId],
  }),
}));

export const devicesRelations = relations(devices, ({ one, many }) => ({
  user: one(users, {
    fields: [devices.userId],
    references: [users.id],
  }),
  pairSessions: many(pairSessions),
  tasks: many(tasks),
  chatSessions: many(chatSessions),
}));

export const userAvatarsRelations = relations(userAvatars, ({ one }) => ({
  user: one(users, {
    fields: [userAvatars.userId],
    references: [users.id],
  }),
}));
