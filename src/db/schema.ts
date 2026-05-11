import { relations, sql } from "drizzle-orm";
import {
  boolean,
  index,
  integer,
  jsonb,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uuid,
  varchar,
} from "drizzle-orm/pg-core";
import {
  aiInvocationStatusValues,
  aiProviderValues,
  auditActorTypeValues,
  auditStatusValues,
  artifactKindValues,
  connectionProviderValues,
  deviceTypeValues,
  integrationAuthTypeValues,
  integrationConnectionStatusValues,
  mcpAuthTypeValues,
  mcpServerStatusValues,
  mcpTransportValues,
  oauthStateStatusValues,
  pairSessionStatusValues,
  runtimeConnectionStatusValues,
  subscriptionStatusValues,
  taskStatusValues,
  userRoleValues,
} from "../contracts/domain.js";

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

export const users = pgTable(
  "users",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    email: varchar("email", { length: 320 }).notNull().unique(),
    passwordHash: text("password_hash").notNull(),
    displayName: varchar("display_name", { length: 120 }),
    role: userRoleEnum("role").notNull().default("user"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    emailIdx: index("users_email_idx").on(table.email),
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
    connectedAt: timestamp("connected_at", { withTimezone: true }).notNull().defaultNow(),
    lastHeartbeatAt: timestamp("last_heartbeat_at", { withTimezone: true }).notNull().defaultNow(),
    disconnectedAt: timestamp("disconnected_at", { withTimezone: true }),
  },
  (table) => ({
    deviceIdx: index("runtime_connections_device_idx").on(table.deviceId),
    userIdx: index("runtime_connections_user_idx").on(table.userId),
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
    requestedCapabilities: jsonb("requested_capabilities").notNull().default(sql`'[]'::jsonb`),
    preferredAiProvider: aiProviderEnum("preferred_ai_provider"),
    status: taskStatusEnum("status").notNull().default("queued"),
    queuePosition: integer("queue_position").notNull().default(0),
    summary: text("summary"),
    error: text("error"),
    approvalRequest: jsonb("approval_request"),
    result: jsonb("result"),
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
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    taskIdx: index("task_events_task_idx").on(table.taskId),
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
    taskLimitMonthly: integer("task_limit_monthly").notNull().default(100),
    aiCreditsMonthly: integer("ai_credits_monthly").notNull().default(0),
    periodEndsAt: timestamp("period_ends_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("subscriptions_user_idx").on(table.userId),
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

export const integrationConnections = pgTable(
  "integration_connections",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    provider: connectionProviderEnum("provider").notNull(),
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
    connectionIdx: index("integration_credentials_connection_idx").on(table.connectionId),
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
    payload: jsonb("payload").notNull().default(sql`'{}'::jsonb`),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("audit_logs_user_idx").on(table.userId),
    actorIdx: index("audit_logs_actor_idx").on(table.actorType, table.actorId),
  }),
);

export const usageRecords = pgTable(
  "usage_records",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    taskId: uuid("task_id").references(() => tasks.id, { onDelete: "set null" }),
    metric: varchar("metric", { length: 80 }).notNull(),
    quantity: integer("quantity").notNull().default(0),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (table) => ({
    userIdx: index("usage_records_user_idx").on(table.userId),
    taskIdx: index("usage_records_task_idx").on(table.taskId),
  }),
);

export const usersRelations = relations(users, ({ many, one }) => ({
  sessions: many(sessions),
  devices: many(devices),
  aiProviderCredentials: many(aiProviderCredentials),
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
}));
