/**
 * Hosted control-plane migration runner.
 * Layer: database + control-plane. Critical bootstrap script for initializing PostgreSQL schema.
 */
import { getControlPlanePool } from '@/core/control-plane/database';
import { applyControlPlaneMigrations } from '@/core/control-plane/migrations';
import { env } from '@/lib/env';

async function main() {
  if (!env.DATABASE_URL) {
    throw new Error('DATABASE_URL is required to run hosted control-plane migrations');
  }

  const pool = getControlPlanePool(env.DATABASE_URL);
  await applyControlPlaneMigrations(pool);
  await pool.end();
  console.log('Control-plane PostgreSQL migrations are up to date.');
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
