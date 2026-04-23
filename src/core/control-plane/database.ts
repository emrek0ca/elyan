import { Pool } from 'pg';
import { env } from '@/lib/env';

let sharedPool: Pool | null = null;
let sharedDatabaseUrl: string | null = null;

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
    sharedPool = new Pool({ connectionString: databaseUrl });
    sharedDatabaseUrl = databaseUrl;
  }

  return sharedPool;
}

export async function closeControlPlanePool() {
  if (sharedPool) {
    await sharedPool.end();
    sharedPool = null;
    sharedDatabaseUrl = null;
  }
}
