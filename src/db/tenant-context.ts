import { sql } from "drizzle-orm";
import type { FastifyInstance } from "fastify";

export type TenantDb = FastifyInstance["db"];

const SAFE_TENANT_KEY_PART = /[^a-zA-Z0-9:_@.-]/g;

function normalizeTenantKeyPart(value: string | number | boolean): string {
  const normalized = String(value).trim().replace(SAFE_TENANT_KEY_PART, "_");
  return normalized.slice(0, 180) || "empty";
}

export async function setTenantContext(
  db: TenantDb,
  input: { userId: string },
): Promise<void> {
  await db.execute(sql`select set_config('app.user_id', ${input.userId}, true)`);
}

export function buildTenantNamespace(input: { userId: string }): string {
  return `tenant:${normalizeTenantKeyPart(input.userId)}`;
}

export function buildTenantCacheKey(input: {
  userId: string;
  scope: string;
  parts?: Array<string | number | boolean | null | undefined>;
}): string {
  const parts = (input.parts ?? [])
    .filter((part): part is string | number | boolean => part !== null && part !== undefined)
    .map(normalizeTenantKeyPart);
  return [buildTenantNamespace({ userId: input.userId }), normalizeTenantKeyPart(input.scope), ...parts].join(":");
}

export function assertTenantMatch(input: {
  expectedUserId: string;
  actualUserId: string | null | undefined;
  resource: string;
}): void {
  if (!input.actualUserId || input.actualUserId !== input.expectedUserId) {
    throw new Error(`${input.resource}_tenant_mismatch`);
  }
}

export async function withTenantTransaction<T>(
  app: FastifyInstance,
  userId: string,
  run: (db: TenantDb) => Promise<T>,
): Promise<T> {
  return app.db.transaction(async (tx) => {
    const db = tx as TenantDb;
    await setTenantContext(db, { userId });
    return run(db);
  });
}
