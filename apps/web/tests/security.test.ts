import { NextRequest } from 'next/server';
import { describe, expect, it } from 'vitest';
import {
  getAllowedApiOrigins,
  getBaseSecurityHeaders,
  getPrivateSurfaceHeaders,
  isAllowedApiOrigin,
} from '@/lib/security';
import { config, middleware } from '@/middleware';

describe('security helpers', () => {
  it('keeps the default origin allowlist explicit and deduplicated', () => {
    const origins = getAllowedApiOrigins('http://localhost:3000, https://elyan.dev , http://localhost:3000');

    expect(origins).toContain('https://elyan.dev');
    expect(origins).toContain('http://localhost:3000');
    expect(origins.filter((origin) => origin === 'http://localhost:3000')).toHaveLength(1);
    expect(isAllowedApiOrigin('https://elyan.dev', origins)).toBe(true);
    expect(isAllowedApiOrigin('https://evil.example', origins)).toBe(false);
  });

  it('adds production-only transport hardening and private surface cache controls', () => {
    const productionHeaders = getBaseSecurityHeaders(true);
    const privateHeaders = getPrivateSurfaceHeaders();

    expect(productionHeaders.some((header) => header.key === 'Strict-Transport-Security')).toBe(true);
    expect(privateHeaders).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'Cache-Control', value: 'no-store, max-age=0' }),
        expect.objectContaining({ key: 'X-Robots-Tag', value: 'noindex, nofollow, noarchive' }),
      ])
    );
  });
});

describe('api middleware hardening', () => {
  it('allows preflight requests from approved origins', async () => {
    const request = new NextRequest('http://127.0.0.1:3000/api/chat', {
      method: 'OPTIONS',
      headers: {
        origin: 'http://localhost:3000',
      },
    });

    const response = await middleware(request);

    expect(response.status).toBe(204);
    expect(response.headers.get('access-control-allow-origin')).toBe('http://localhost:3000');
    expect(response.headers.get('x-frame-options')).toBe('DENY');
  });

  it('rejects preflight requests from unapproved origins', async () => {
    const request = new NextRequest('http://127.0.0.1:3000/api/chat', {
      method: 'OPTIONS',
      headers: {
        origin: 'https://evil.example',
      },
    });

    const response = await middleware(request);

    expect(response.status).toBe(403);
    expect(response.headers.get('access-control-allow-origin')).toBeNull();
    expect(response.headers.get('x-frame-options')).toBe('DENY');
  });

  it('routes hosted panel pages through middleware without protecting local runtime pages', async () => {
    expect(config.matcher).toContain('/panel/:path*');
    expect(config.matcher).not.toContain('/manage/:path*');
    const manageRequest = new NextRequest('http://127.0.0.1:3000/manage');
    const manageResponse = await middleware(manageRequest);

    expect(manageResponse.status).toBe(200);
  });
});
