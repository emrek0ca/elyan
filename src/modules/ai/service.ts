import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { aiProviderCredentials, aiProviderInvocations } from "../../db/schema.js";
import type { AiProvider } from "../../contracts/domain.js";
import { encryptJson } from "../../lib/crypto-seal.js";
import { badRequest } from "../../lib/errors.js";
import { createAuditLog } from "../audit/service.js";
import { buildGroqModelCatalog } from "../brain/groq-models.js";
import { supportedAiProviders } from "./provider-registry.js";
import { resolveAiRoute } from "./routing.js";

export async function listAiProviderRegistryForUser(app: FastifyInstance, userId: string) {
  const credentialRows = await app.db
    .select({
      provider: aiProviderCredentials.provider,
      label: aiProviderCredentials.label,
      defaultModel: aiProviderCredentials.defaultModel,
      baseUrl: aiProviderCredentials.baseUrl,
      updatedAt: aiProviderCredentials.updatedAt,
    })
    .from(aiProviderCredentials)
    .where(eq(aiProviderCredentials.userId, userId));

  const configuredByProvider = new Map(credentialRows.map((row) => [row.provider, row]));
  const groqCatalog = buildGroqModelCatalog(app.config);

  return supportedAiProviders.map((provider) => ({
    code: provider.code,
    displayName: provider.displayName,
    hosted: provider.hosted,
    workloads: provider.workloads,
    models: provider.code === "groq" ? groqCatalog.models : provider.models,
    configured: configuredByProvider.has(provider.code),
    defaultModel:
      configuredByProvider.get(provider.code)?.defaultModel ??
      (provider.code === "groq" ? groqCatalog.reasoningModel : provider.defaultModelByWorkload.planning),
    baseUrl: configuredByProvider.get(provider.code)?.baseUrl ?? null,
    label: configuredByProvider.get(provider.code)?.label ?? null,
  }));
}

export async function listAiProviderCredentials(app: FastifyInstance, userId: string) {
  const rows = await app.db
    .select({
      id: aiProviderCredentials.id,
      provider: aiProviderCredentials.provider,
      label: aiProviderCredentials.label,
      defaultModel: aiProviderCredentials.defaultModel,
      baseUrl: aiProviderCredentials.baseUrl,
      metadata: aiProviderCredentials.metadata,
      updatedAt: aiProviderCredentials.updatedAt,
    })
    .from(aiProviderCredentials)
    .where(eq(aiProviderCredentials.userId, userId))
    .orderBy(desc(aiProviderCredentials.updatedAt));

  return rows.filter((row) => row.provider === "groq");
}

export async function upsertAiProviderCredential(
  app: FastifyInstance,
  input: {
    userId: string;
    provider: AiProvider;
    label?: string;
    apiKey?: string;
    baseUrl?: string;
    defaultModel?: string;
    metadata?: Record<string, unknown>;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  if (input.provider !== "groq") {
    throw badRequest("Only Groq is supported on the server control plane");
  }

  if (!input.apiKey) {
    throw badRequest(`${input.provider} requires apiKey`);
  }

  const encryptedPayload = encryptJson(app.config, {
    apiKey: input.apiKey ?? null,
  });

  const existingRows = await app.db
    .select({
      id: aiProviderCredentials.id,
      provider: aiProviderCredentials.provider,
    })
    .from(aiProviderCredentials)
    .where(and(eq(aiProviderCredentials.userId, input.userId), eq(aiProviderCredentials.provider, input.provider)));

  const existing = existingRows[0];

  const rows =
    existing
      ? await app.db
          .update(aiProviderCredentials)
          .set({
            label: input.label,
            encryptedPayload,
            defaultModel: input.defaultModel,
            baseUrl: input.baseUrl,
            metadata: input.metadata ?? {},
            updatedAt: new Date(),
          })
          .where(eq(aiProviderCredentials.id, existing.id))
          .returning()
      : await app.db
          .insert(aiProviderCredentials)
          .values({
            userId: input.userId,
            provider: input.provider,
            label: input.label,
            encryptedPayload,
            defaultModel: input.defaultModel,
            baseUrl: input.baseUrl,
            metadata: input.metadata ?? {},
          })
          .returning();

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "ai.credential.upsert",
    resourceType: "ai_provider_credential",
    resourceId: rows[0]?.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      provider: input.provider,
    },
  });

  return rows[0];
}

export async function deleteAiProviderCredential(
  app: FastifyInstance,
  input: {
    userId: string;
    provider: AiProvider;
    ipAddress?: string;
    userAgent?: string;
  },
) {
  if (input.provider !== "groq") {
    throw badRequest("Only Groq is supported on the server control plane");
  }

  const rows = await app.db
    .delete(aiProviderCredentials)
    .where(and(eq(aiProviderCredentials.userId, input.userId), eq(aiProviderCredentials.provider, input.provider)))
    .returning({
      id: aiProviderCredentials.id,
      provider: aiProviderCredentials.provider,
    });

  const deleted = rows[0] ?? null;

  await createAuditLog(app, {
    userId: input.userId,
    actorType: "user",
    actorId: input.userId,
    action: "ai.credential.delete",
    resourceType: "ai_provider_credential",
    resourceId: deleted?.id,
    status: "success",
    ipAddress: input.ipAddress,
    userAgent: input.userAgent,
    payload: {
      provider: input.provider,
    },
  });

  return {
    deleted: Boolean(deleted),
  };
}

export async function listAiUsage(app: FastifyInstance, userId: string, limit: number) {
  return app.db
    .select()
    .from(aiProviderInvocations)
    .where(eq(aiProviderInvocations.userId, userId))
    .orderBy(desc(aiProviderInvocations.createdAt))
    .limit(limit);
}

export function previewAiRoute(input: Parameters<typeof resolveAiRoute>[0]) {
  return resolveAiRoute(input);
}
