import { describe, expect, it, vi } from 'vitest';

vi.mock('next-auth/jwt', () => ({
  getToken: vi.fn(),
}));

vi.mock('@/lib/env', () => ({
  env: {
    NEXTAUTH_SECRET: 'test-secret',
    DATABASE_URL: 'postgres://localhost/elyan',
    NEXTAUTH_URL: 'https://api.elyan.dev',
  },
}));

import { getToken } from 'next-auth/jwt';
import { getControlPlaneAuthOptions } from '@/core/control-plane/auth';
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

  it('uses secure cross-subdomain cookie settings for hosted auth', () => {
    const options = getControlPlaneAuthOptions();
    const sessionToken = options.cookies?.sessionToken;
    const csrfToken = options.cookies?.csrfToken;

    expect(sessionToken?.options.domain).toBe('.elyan.dev');
    expect(sessionToken?.options.sameSite).toBe('none');
    expect(sessionToken?.options.secure).toBe(true);
    expect(csrfToken?.options.domain).toBe('.elyan.dev');
    expect(csrfToken?.name).toBe('__Secure-next-auth.csrf-token');
  });
});
