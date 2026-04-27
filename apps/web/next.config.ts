import type { NextConfig } from 'next';
import { getBaseSecurityHeaders, getPrivateSurfaceHeaders } from './src/lib/security';

const baseSecurityHeaders = getBaseSecurityHeaders();
const privateSecurityHeaders = [...baseSecurityHeaders, ...getPrivateSurfaceHeaders()];

const nextConfig: NextConfig = {
  // Produces .next/standalone for the direct local Node runtime and optional packaging.
  output: 'standalone',
  outputFileTracingExcludes: {
    '/**': ['storage/**/*'],
  },
  poweredByHeader: false,
  async headers() {
    return [
      { source: '/auth', headers: privateSecurityHeaders },
      { source: '/manage', headers: privateSecurityHeaders },
      { source: '/panel', headers: privateSecurityHeaders },
      { source: '/panel/:path*', headers: privateSecurityHeaders },
      { source: '/api/auth/:path*', headers: privateSecurityHeaders },
      { source: '/api/control-plane/:path*', headers: privateSecurityHeaders },
      { source: '/:path*', headers: baseSecurityHeaders },
    ];
  },
};

export default nextConfig;
