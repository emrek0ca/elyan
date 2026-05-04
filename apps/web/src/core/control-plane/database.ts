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

export type ControlPlaneDatabaseHealthSnapshot = {
  storage: 'file' | 'postgres';
  mode: 'file_backed' | 'postgres';
  configured: boolean;
  ready: boolean;
  detail: string;
  totalCount?: number;
  idleCount?: number;
  waitingCount?: number;
  maxCount?: number;
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

export function buildControlPlaneDatabaseHealthSnapshot(
  storage: 'file' | 'postgres',
  stats = getControlPlanePoolStats()
): ControlPlaneDatabaseHealthSnapshot {
  if (storage === 'file') {
    const production = process.env.NODE_ENV === 'production';
    return {
      storage,
      mode: 'file_backed',
      configured: false,
      ready: !production,
      detail: production
        ? 'File-backed state store is disabled in production. Set DATABASE_URL and run migrations.'
        : 'File-backed state store is active for local development and tests.',
    };
  }

  if (stats) {
    return {
      storage,
      mode: 'postgres',
      configured: true,
      ready: true,
      detail: 'PostgreSQL pool is active and handling hosted control-plane state.',
      ...stats,
    };
  }

  return {
    storage,
    mode: 'postgres',
    configured: true,
    ready: false,
    detail: 'PostgreSQL is configured, but the shared pool is not ready yet.',
  };
}

export async function closeControlPlanePool() {
  if (sharedPool) {
    await sharedPool.end();
    sharedPool = null;
    sharedDatabaseUrl = null;
  }
}
