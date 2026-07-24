const DEFAULT_API_BASE_URL = 'https://api.elyan.dev';
const DEFAULT_WEB_ORIGIN = 'http://localhost:4321';

function normalizedUrl(value: string | undefined, fallback: string): URL {
  const url = new URL(String(value || fallback).trim());
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('elyan_invalid_server_url');
  }
  url.pathname = url.pathname.replace(/\/+$/, '');
  url.search = '';
  url.hash = '';
  return url;
}

export function getApiBaseUrl(): URL {
  const url = normalizedUrl(process.env.ELYAN_API_BASE_URL, DEFAULT_API_BASE_URL);
  if (process.env.NODE_ENV === 'production' && url.protocol !== 'https:') {
    throw new Error('elyan_api_requires_https');
  }
  return url;
}

export function getWebOrigin(): string {
  const url = normalizedUrl(process.env.ELYAN_WEB_ORIGIN, DEFAULT_WEB_ORIGIN);
  if (process.env.NODE_ENV === 'production' && url.protocol !== 'https:') {
    throw new Error('elyan_web_requires_https');
  }
  return url.origin;
}

export function isProduction(): boolean {
  return process.env.NODE_ENV === 'production';
}

export function getWebSessionSecret(): string {
  const value = String(process.env.ELYAN_WEB_SESSION_SECRET || '').trim();
  if (isProduction() && value.length < 32) {
    throw new Error('elyan_web_session_secret_required');
  }
  return value || 'elyan-local-development-session-secret';
}

export const UPSTREAM_TIMEOUT_MS = 20_000;
export const STREAM_CONNECT_TIMEOUT_MS = 15_000;
