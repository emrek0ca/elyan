import { randomUUID } from 'node:crypto';

export type PublicError = { error: string; message: string; requestId?: string };

const publicMessages: Record<string, string> = {
  invalid_credentials: 'Email or password is incorrect.',
  two_factor_required: 'Enter your two-factor authentication code.',
  two_factor_invalid: 'The two-factor authentication code is invalid.',
  email_already_exists: 'An account already exists for this email.',
  validation_error: 'Please check the entered information.',
  rate_limit_exceeded: 'Too many attempts. Please wait and try again.',
  request_rejected: 'The request could not be verified. Refresh the page and try again.',
  payload_too_large: 'The request body is too large.',
  unauthorized: 'Your session has expired. Please sign in again.',
};

export function requestId(): string {
  return randomUUID();
}

export function normalizePublicError(value: unknown, status = 500, fallbackRequestId?: string): PublicError {
  const input = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const rawCode = String(input.error || input.code || '').trim().toLowerCase();
  const code = /^[a-z0-9_-]{2,80}$/.test(rawCode) ? rawCode : status === 401 ? 'unauthorized' : 'request_failed';
  const upstreamMessage = String(input.message || '').trim();
  const safeUpstream = status < 500 && upstreamMessage.length > 0 && upstreamMessage.length <= 240 ? upstreamMessage : '';
  return {
    error: code,
    message: publicMessages[code] || safeUpstream || (status >= 500 ? 'Elyan is temporarily unavailable. Please try again.' : 'The request could not be completed.'),
    requestId: String(input.requestId || fallbackRequestId || '').trim() || undefined,
  };
}

export function json(data: unknown, status = 200, headers?: HeadersInit): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store, max-age=0',
      pragma: 'no-cache',
      ...headers,
    },
  });
}

export async function readJsonSafe(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return {};
  try { return JSON.parse(text); } catch { return {}; }
}
