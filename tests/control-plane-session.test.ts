import { describe, expect, it, vi } from 'vitest';

vi.mock('next-auth/jwt', () => ({
  getToken: vi.fn(),
}));

vi.mock('@/lib/env', () => ({
  env: {
    NEXTAUTH_SECRET: 'test-secret',
    DATABASE_URL: 'postgres://localhost/elyan',
  },
}));

import { getToken } from 'next-auth/jwt';
import { getControlPlaneSessionToken } from '@/core/control-plane/session';

describe('control-plane session contract', () => {
  it('maps Auth.js JWT session claims into Elyan session claims', async () => {
    vi.mocked(getToken).mockResolvedValue({
      sub: 'usr_1',
      email: 'ayla@example.com',
      name: 'Ayla',
      accountId: 'acct_1',
      ownerType: 'individual',
      role: 'owner',
      planId: 'cloud_assisted',
    } as never);

    const token = await getControlPlaneSessionToken({
      cookies: { get: () => undefined },
    } as never);

    expect(token).toEqual({
      sub: 'usr_1',
      email: 'ayla@example.com',
      name: 'Ayla',
      accountId: 'acct_1',
      ownerType: 'individual',
      role: 'owner',
      planId: 'cloud_assisted',
    });
  });
});
