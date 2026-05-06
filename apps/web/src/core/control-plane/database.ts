/**
 * PostgreSQL pool and hosted-control-plane DB health checks.
 * Layer: database + control-plane. Critical infrastructure for all hosted state reads and writes.
 */
import { Pool, type PoolConfig } from 'pg';
import { env } from '@/lib/env';
import { readControlPlaneMigrationStatus } from './migrations';

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
  activeDatabaseMode: 'file_backed' | 'postgres';
  configured: boolean;
  postgresReachable: boolean;
  migrationsApplied: boolean;
  schemaReady: boolean;
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

export async function buildControlPlaneDatabaseHealthSnapshot(
  storage: 'file' | 'postgres',
  stats?: ReturnType<typeof getControlPlanePoolStats>
): Promise<ControlPlaneDatabaseHealthSnapshot> {
  if (storage === 'file') {
    const production = process.env.NODE_ENV === 'production';
    return {
      storage,
      mode: 'file_backed',
      activeDatabaseMode: 'file_backed',
      configured: false,
      postgresReachable: false,
      migrationsApplied: false,
      schemaReady: false,
      ready: !production,
      detail: production
        ? 'File-backed state store is disabled in production. Set DATABASE_URL and run migrations.'
        : 'File-backed state store is active for local development and tests.',
    };
  }

  const databaseUrl = getControlPlaneDatabaseUrl();
  const pool = getControlPlanePool(databaseUrl);
  const poolStats = stats ?? getControlPlanePoolStats(databaseUrl);

  try {
    await pool.query('SELECT 1');
  } catch (error) {
    const message = error instanceof Error ? error.message : 'unknown PostgreSQL connectivity failure';

    return {
      storage,
      mode: 'postgres',
      activeDatabaseMode: 'postgres',
      configured: true,
      postgresReachable: false,
      migrationsApplied: false,
      schemaReady: false,
      ready: false,
      detail: `PostgreSQL is configured, but the server is unreachable: ${message}`,
    };
  }

  const migrationStatus = await readControlPlaneMigrationStatus(pool);

  if (poolStats) {
    return {
      storage,
      mode: 'postgres',
      activeDatabaseMode: 'postgres',
      configured: true,
      postgresReachable: true,
      migrationsApplied: migrationStatus.applied,
      schemaReady: migrationStatus.applied,
      ready: migrationStatus.applied,
      detail: migrationStatus.applied
        ? 'PostgreSQL pool is active, schema migrations are applied, and hosted control-plane state is ready.'
        : `PostgreSQL is reachable, but schema migrations are incomplete: ${migrationStatus.missingVersions
            .map((migration) => `${migration.version}:${migration.name}`)
            .join(', ')}`,
      ...poolStats,
    };
  }

  return {
    storage,
    mode: 'postgres',
    activeDatabaseMode: 'postgres',
    configured: true,
    postgresReachable: true,
    migrationsApplied: migrationStatus.applied,
    schemaReady: migrationStatus.applied,
    ready: migrationStatus.applied,
    detail: migrationStatus.applied
      ? 'PostgreSQL is configured and schema migrations are applied, but the shared pool is not ready yet.'
      : `PostgreSQL is reachable, but schema migrations are incomplete: ${migrationStatus.missingVersions
          .map((migration) => `${migration.version}:${migration.name}`)
          .join(', ')}`,
  };
}

export async function closeControlPlanePool() {
  if (sharedPool) {
    await sharedPool.end();
    sharedPool = null;
    sharedDatabaseUrl = null;
  }
}
