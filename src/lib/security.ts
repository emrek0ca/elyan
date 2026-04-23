export type HeaderEntry = Readonly<{
  key: string;
  value: string;
}>;

const DEFAULT_ALLOWED_API_ORIGINS = [
  'https://elyan.dev',
  'https://api.elyan.dev',
  'http://localhost:3000',
  'http://localhost:3010',
  'http://127.0.0.1:3000',
  'http://127.0.0.1:3010',
] as const;

const BASE_SECURITY_HEADERS: HeaderEntry[] = [
  { key: 'X-DNS-Prefetch-Control', value: 'off' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  {
    key: 'Permissions-Policy',
    value: 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
  },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
  { key: 'Cross-Origin-Resource-Policy', value: 'same-origin' },
];

const PRIVATE_SURFACE_HEADERS: HeaderEntry[] = [
  { key: 'Cache-Control', value: 'no-store, max-age=0' },
  { key: 'Pragma', value: 'no-cache' },
  { key: 'Expires', value: '0' },
  { key: 'X-Robots-Tag', value: 'noindex, nofollow, noarchive' },
];

export const CORS_ALLOWED_METHODS = 'GET,POST,PUT,PATCH,DELETE,OPTIONS';
export const CORS_ALLOWED_HEADERS =
  'Content-Type, Authorization, X-Requested-With, X-CSRF-Token, X-IYZ-SIGNATURE-V3, x-elyan-device-token, x-elyan-device-id, next-auth.csrf-token, next-auth.callback-url';

export function getAllowedApiOrigins(rawValue = process.env.ELYAN_ALLOWED_ORIGINS) {
  const origins = new Set<string>(DEFAULT_ALLOWED_API_ORIGINS);

  if (rawValue) {
    for (const origin of rawValue.split(',')) {
      const normalized = origin.trim();
      if (normalized) {
        origins.add(normalized);
      }
    }
  }

  return [...origins];
}

export function isAllowedApiOrigin(origin: string | null, allowedOrigins = getAllowedApiOrigins()) {
  if (!origin) {
    return false;
  }

  return allowedOrigins.includes(origin.trim());
}

export function getBaseSecurityHeaders(includeHsts = process.env.NODE_ENV === 'production') {
  return includeHsts
    ? [...BASE_SECURITY_HEADERS, { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' }]
    : [...BASE_SECURITY_HEADERS];
}

export function getPrivateSurfaceHeaders() {
  return [...PRIVATE_SURFACE_HEADERS];
}

export function applyHeaderEntries(headers: Headers, entries: ReadonlyArray<HeaderEntry>) {
  for (const entry of entries) {
    headers.set(entry.key, entry.value);
  }
}

export function applyCorsHeaders(headers: Headers, origin: string) {
  headers.set('Access-Control-Allow-Origin', origin);
  headers.set('Access-Control-Allow-Credentials', 'true');
  headers.set('Access-Control-Allow-Methods', CORS_ALLOWED_METHODS);
  headers.set('Access-Control-Allow-Headers', CORS_ALLOWED_HEADERS);
  headers.set('Access-Control-Max-Age', '86400');

  const vary = headers.get('Vary');
  headers.set('Vary', vary ? `${vary}, Origin` : 'Origin');
}
