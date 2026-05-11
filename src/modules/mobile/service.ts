import { desc, eq, inArray, sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { aiProviderCredentials, integrationConnections, mcpServers, subscriptions, tasks, users } from "../../db/schema.js";
import { listUserDevices } from "../devices/service.js";
import { supportedAiProviders } from "../ai/provider-registry.js";

export async function getMobileBootstrap(app: FastifyInstance, userId: string) {
  const [userRows, subscriptionRows, devices, taskRows, integrationRows, mcpRows, aiCredentialRows, pendingCounts] =
    await Promise.all([
      app.db
        .select({
          id: users.id,
          email: users.email,
          displayName: users.displayName,
          role: users.role,
          createdAt: users.createdAt,
        })
        .from(users)
        .where(eq(users.id, userId))
        .limit(1),
      app.db.select().from(subscriptions).where(eq(subscriptions.userId, userId)).limit(1),
      listUserDevices(app, userId),
      app.db
        .select({
          id: tasks.id,
          title: tasks.title,
          status: tasks.status,
          targetDeviceId: tasks.targetDeviceId,
          queuePosition: tasks.queuePosition,
          createdAt: tasks.createdAt,
          updatedAt: tasks.updatedAt,
        })
        .from(tasks)
        .where(eq(tasks.userId, userId))
        .orderBy(desc(tasks.createdAt))
        .limit(10),
      app.db
        .select({
          id: integrationConnections.id,
          provider: integrationConnections.provider,
          status: integrationConnections.status,
          displayName: integrationConnections.displayName,
          capabilities: integrationConnections.capabilities,
          updatedAt: integrationConnections.updatedAt,
        })
        .from(integrationConnections)
        .where(eq(integrationConnections.userId, userId))
        .orderBy(desc(integrationConnections.updatedAt)),
      app.db
        .select({
          id: mcpServers.id,
          name: mcpServers.name,
          transport: mcpServers.transport,
          status: mcpServers.status,
          capabilities: mcpServers.capabilities,
          updatedAt: mcpServers.updatedAt,
        })
        .from(mcpServers)
        .where(eq(mcpServers.userId, userId))
        .orderBy(desc(mcpServers.updatedAt)),
      app.db
        .select({
          provider: aiProviderCredentials.provider,
          defaultModel: aiProviderCredentials.defaultModel,
          updatedAt: aiProviderCredentials.updatedAt,
        })
        .from(aiProviderCredentials)
        .where(eq(aiProviderCredentials.userId, userId)),
      app.db
        .select({
          pendingApprovals: sql<number>`count(*) filter (where ${tasks.status} = 'waiting_approval')`,
          activeTasks: sql<number>`count(*) filter (where ${tasks.status} in ('queued', 'planning', 'running', 'waiting_approval'))`,
        })
        .from(tasks)
        .where(eq(tasks.userId, userId)),
    ]);

  const configuredAiProviders = new Map(aiCredentialRows.map((row) => [row.provider, row]));

  return {
    user: userRows[0] ?? null,
    subscription: subscriptionRows[0] ?? null,
    devices,
    recentTasks: taskRows,
    integrations: integrationRows,
    mcpServers: mcpRows,
    aiProviders: supportedAiProviders.map((provider) => ({
      code: provider.code,
      displayName: provider.displayName,
      hosted: provider.hosted,
      configured: configuredAiProviders.has(provider.code),
      defaultModel: configuredAiProviders.get(provider.code)?.defaultModel ?? provider.defaultModelByWorkload.planning,
      models: provider.models,
    })),
    summary: {
      pendingApprovals: Number(pendingCounts[0]?.pendingApprovals ?? 0),
      activeTasks: Number(pendingCounts[0]?.activeTasks ?? 0),
      connectedDesktops: devices.filter((device) => device.type === "desktop" && device.runtime.isConnected).length,
    },
  };
}
