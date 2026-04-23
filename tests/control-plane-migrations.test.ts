import { describe, expect, it, vi } from 'vitest';
import {
  assertControlPlaneMigrationsApplied,
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
