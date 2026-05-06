import type { NextConfig } from 'next';
import path from 'path';
import { getBaseSecurityHeaders, getPrivateSurfaceHeaders } from './src/lib/security';

const baseSecurityHeaders = getBaseSecurityHeaders();
const privateSecurityHeaders = [...baseSecurityHeaders, ...getPrivateSurfaceHeaders()];

const nextConfig: NextConfig = {
  turbopack: {
    root: path.resolve(__dirname),
  },
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
