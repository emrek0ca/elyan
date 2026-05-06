import { describe, expect, it, vi } from 'vitest';
import {
  assertControlPlaneMigrationsApplied,
  canonicalSharedTruthRelations,
  getControlPlaneMigrationVersions,
} from '@/core/control-plane/migrations';
import { ControlPlaneConfigurationError } from '@/core/control-plane/errors';

function createPool(appliedVersions: number[] = [], hasTable = true) {
  return {
    connect: async () => {
      const queries: string[] = [];
      return {
        queries,
        query: async (sql: string) => {
          queries.push(sql);

          if (sql.includes('to_regclass')) {
            return {
              rows: [{ exists: hasTable ? 'schema_migrations' : null }],
            } as const;
          }

          if (sql.includes('SELECT version FROM schema_migrations')) {
            return {
              rows: appliedVersions.map((version) => ({ version })),
            } as const;
          }

          return { rows: [] } as const;
        },
        release: vi.fn(),
      };
    },
  } as const;
}

describe('control-plane migrations', () => {
  it('expects the schema migration gate to be populated', () => {
    expect(getControlPlaneMigrationVersions().length).toBeGreaterThan(0);
  });

  it('declares the canonical shared truth relations without private runtime state', () => {
    expect(canonicalSharedTruthRelations).toEqual(
      expect.arrayContaining([
        'users',
        'accounts',
        'sessions',
        'verification_token',
        'subscriptions',
        'entitlements',
        'token_ledger',
        'usage_counters',
        'usage_events',
        'billing_profiles',
        'notifications',
        'device_link_requests',
        'devices',
        'release_cache',
        'learning_events',
        'model_artifacts',
        'retrieval_documents',
        'schema_migrations',
      ])
    );
    expect(canonicalSharedTruthRelations).not.toEqual(
      expect.arrayContaining(['local_memory', 'local_files', 'runtime_internal_state', 'private_context'])
    );
  });

  it('fails closed when schema_migrations is missing', async () => {
    await expect(assertControlPlaneMigrationsApplied(createPool([], false) as never)).rejects.toBeInstanceOf(
      ControlPlaneConfigurationError
    );
  });

  it('passes only when every migration is applied', async () => {
    await expect(
      assertControlPlaneMigrationsApplied(createPool(getControlPlaneMigrationVersions()) as never)
    ).resolves.toBeUndefined();
  });
});
