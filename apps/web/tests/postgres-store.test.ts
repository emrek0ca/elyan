import { beforeEach, describe, expect, it, vi } from 'vitest';

const { fakeClient, fakePool } = vi.hoisted(() => {
  const fakeClient = {
    query: vi.fn(async () => ({ rows: [] })),
    release: vi.fn(),
  };

  const fakePool = {
    connect: vi.fn(async () => fakeClient),
  };

  return { fakeClient, fakePool };
});

vi.mock('@/core/control-plane/database', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/core/control-plane/database')>();
  return {
    ...actual,
    getControlPlanePool: vi.fn(() => fakePool),
  };
});

vi.mock('@/core/control-plane/migrations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/core/control-plane/migrations')>();
  return {
    ...actual,
    assertControlPlaneMigrationsApplied: vi.fn(),
  };
});

import { ControlPlaneConfigurationError } from '@/core/control-plane/errors';
import { createDefaultControlPlaneState } from '@/core/control-plane/defaults';
import { assertControlPlaneMigrationsApplied } from '@/core/control-plane/migrations';
import { PostgresControlPlaneStateStore, runClientQueriesSequentially } from '@/core/control-plane/postgres-store';

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(assertControlPlaneMigrationsApplied).mockReset();
});

describe('runClientQueriesSequentially', () => {
  it('waits for each query before starting the next one', async () => {
    let activeQueries = 0;
    let maxActiveQueries = 0;
    const order: string[] = [];

    const client = {
      async query(label: string) {
        activeQueries += 1;
        maxActiveQueries = Math.max(maxActiveQueries, activeQueries);
        order.push(`start:${label}`);
        await new Promise((resolve) => setTimeout(resolve, 5));
        order.push(`end:${label}`);
        activeQueries -= 1;
        return { rows: [{ label }] };
      },
    };

    const results = await runClientQueriesSequentially(client, [
      () => client.query('accounts'),
      () => client.query('subscriptions'),
      () => client.query('users'),
    ]);

    expect(maxActiveQueries).toBe(1);
    expect(order).toEqual([
      'start:accounts',
      'end:accounts',
      'start:subscriptions',
      'end:subscriptions',
      'start:users',
      'end:users',
    ]);
    expect(results.map((result) => result.rows[0]?.label)).toEqual(['accounts', 'subscriptions', 'users']);
  });
});

describe('PostgresControlPlaneStateStore', () => {
  it('retries bootstrap after a transient migration failure', async () => {
    vi.mocked(assertControlPlaneMigrationsApplied)
      .mockRejectedValueOnce(new ControlPlaneConfigurationError('Control-plane PostgreSQL migrations are incomplete.'))
      .mockResolvedValueOnce(undefined);

    const store = new PostgresControlPlaneStateStore({ databaseUrl: 'postgres://example' });
    const readStateSpy = vi.spyOn(store as never, 'readState').mockResolvedValue(createDefaultControlPlaneState());

    await expect(store.read()).rejects.toThrow('Control-plane PostgreSQL migrations are incomplete.');
    await expect(store.read()).resolves.toMatchObject({ version: 6 });
    expect(vi.mocked(assertControlPlaneMigrationsApplied)).toHaveBeenCalledTimes(2);
    expect(readStateSpy).toHaveBeenCalledTimes(1);
  });
});
