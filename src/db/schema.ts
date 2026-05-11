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
  aiProviderValues,
  artifactKindValues,
  deviceTypeValues,
  pairSessionStatusValues,
  runtimeConnectionStatusValues,
  subscriptionStatusValues,
  taskStatusValues,
} from "../contracts/domain.js";

export const deviceTypeEnum = pgEnum("device_type", deviceTypeValues);
export const pairSessionStatusEnum = pgEnum("pair_session_status", pairSessionStatusValues);
export const runtimeConnectionStatusEnum = pgEnum("runtime_connection_status", runtimeConnectionStatusValues);
export const taskStatusEnum = pgEnum("task_status", taskStatusValues);
export const artifactKindEnum = pgEnum("artifact_kind", artifactKindValues);
export const subscriptionStatusEnum = pgEnum("subscription_status", subscriptionStatusValues);
export const aiProviderEnum = pgEnum("ai_provider", aiProviderValues);

export const users = pgTable(
  "users",
  {
    id: uuid("id").defaultRandom().primaryKey(),
    email: varchar("email", { length: 320 }).notNull().unique(),
    passwordHash: text("password_hash").notNull(),
    displayName: varchar("display_name", { length: 120 }),
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
