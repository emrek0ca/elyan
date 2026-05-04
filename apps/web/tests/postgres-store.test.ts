import { describe, expect, it } from 'vitest';
import { runClientQueriesSequentially } from '@/core/control-plane/postgres-store';

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
