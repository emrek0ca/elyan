import { Pool, type PoolConfig } from 'pg';
import { env } from '@/lib/env';

let sharedPool: Pool | null = null;
let sharedDatabaseUrl: string | null = null;

const CONTROL_PLANE_POOL_CONFIG: Omit<PoolConfig, 'connectionString'> = {
  application_name: 'elyan-control-plane',
  max: 8,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 5_000,
  keepAlive: true,
  allowExitOnIdle: true,
};

export function getControlPlaneDatabaseUrl(explicitUrl?: string) {
  const databaseUrl = explicitUrl ?? env.DATABASE_URL;
  if (!databaseUrl) {
    throw new Error('DATABASE_URL is required for hosted control-plane PostgreSQL operations');
  }

  return databaseUrl;
}

export function getControlPlanePool(explicitUrl?: string) {
  const databaseUrl = getControlPlaneDatabaseUrl(explicitUrl);

  if (!sharedPool || sharedDatabaseUrl !== databaseUrl) {
    sharedPool = new Pool({
      connectionString: databaseUrl,
      ...CONTROL_PLANE_POOL_CONFIG,
    });
    sharedDatabaseUrl = databaseUrl;
  }

  return sharedPool;
}

export function getControlPlanePoolStats(explicitUrl?: string) {
  const databaseUrl = explicitUrl ?? env.DATABASE_URL;

  if (!databaseUrl || !sharedPool || sharedDatabaseUrl !== databaseUrl) {
    return undefined;
  }

  return {
    totalCount: sharedPool.totalCount,
    idleCount: sharedPool.idleCount,
    waitingCount: sharedPool.waitingCount,
    maxCount: sharedPool.options.max ?? CONTROL_PLANE_POOL_CONFIG.max ?? 0,
  };
}

export async function closeControlPlanePool() {
  if (sharedPool) {
    await sharedPool.end();
    sharedPool = null;
    sharedDatabaseUrl = null;
  }
}
