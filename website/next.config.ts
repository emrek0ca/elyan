import createNextIntlPlugin from 'next-intl/plugin';
import type { NextConfig } from 'next';

const withNextIntl = createNextIntlPlugin('./lib/i18n.ts');

const isDev = process.env.NODE_ENV === 'development';
const isStaticExport =
  process.env.NEXT_OUTPUT_EXPORT === '1' ||
  process.env.npm_lifecycle_event === 'build:dist';

const nextConfig: NextConfig = {
  trailingSlash: true,
  output: isStaticExport ? 'export' : undefined,
  turbopack: {
    root: process.cwd()
  },
  images: {
    unoptimized: true
  },
  ...(isStaticExport
    ? {}
    : {
        async rewrites() {
          if (!isDev) return [];
          return [
            {
              source: '/api/:path*',
              destination: 'https://api.elyan.dev/:path*'
            }
          ];
        }
      })
};

export default withNextIntl(nextConfig);
