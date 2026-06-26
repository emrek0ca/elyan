// Determine the API base URL at runtime:
// - On production (elyan.dev): use the Apache proxy /api → avoids CORS completely
// - On localhost/dev: use the Next.js /api rewrite → keeps browser calls same-origin
function resolveApiBase(): string {
  if (typeof window !== 'undefined') {
    const hostname = window.location.hostname;
    if (
      hostname === 'elyan.dev' ||
      hostname === 'www.elyan.dev' ||
      hostname === '127.0.0.1' ||
      hostname === 'localhost'
    ) {
      // Use Apache reverse proxy (or Next.js dev rewrites) to api.elyan.dev — no CORS issues
      return '/api';
    }
  }
  // Dev / SSR fallback
  return process.env.NEXT_PUBLIC_API_BASE || 'https://api.elyan.dev';
}

export function getApiBaseUrl(): string {
  return resolveApiBase();
}

export function buildApiHeaders(
  currentToken: string | null,
  options: RequestInit = {}
): Headers {
  const headers = new Headers(options.headers);
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  if (options.body != null && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (currentToken) {
    headers.set('Authorization', `Bearer ${currentToken}`);
  }
  return headers;
}

let memoryAccessToken: string | null = null;
let isRefreshing = false;
let refreshSubscribers: ((token: string | null) => void)[] = [];

function onRefreshed(token: string | null) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

function addRefreshSubscriber(cb: (token: string | null) => void) {
  refreshSubscribers.push(cb);
}

export function setAccessToken(token: string | null) {
  memoryAccessToken = token;
}

export function getAccessToken() {
  return memoryAccessToken;
}

export function setRefreshToken(token: string | null) {
  if (typeof window !== 'undefined') {
    if (token) {
      localStorage.setItem('_elyan_rt', btoa(token));
    } else {
      localStorage.removeItem('_elyan_rt');
    }
  }
}

export function getRefreshToken(): string | null {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('_elyan_rt');
    if (token) {
      try {
        return atob(token);
      } catch {
        return null;
      }
    }
  }
  return null;
}

export function clearTokens() {
  memoryAccessToken = null;
  if (typeof window !== 'undefined') {
    localStorage.removeItem('_elyan_rt');
  }
}

function failClosed() {
  clearTokens();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('auth_fail_closed'));
  }
}

export async function refreshAccessToken({
  failClosedOnError = true
}: {
  failClosedOnError?: boolean;
} = {}): Promise<string | null> {
  const rt = getRefreshToken();
  if (!rt) {
    if (failClosedOnError) {
      failClosed();
    }
    return null;
  }

  try {
    const apiBase = resolveApiBase();
    const res = await fetch(`${apiBase}/v1/auth/refresh`, {
      method: 'POST',
      mode: apiBase.startsWith('/') ? 'same-origin' : 'cors',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify({ refreshToken: rt }),
    });

    if (!res.ok) {
      throw new Error('Refresh failed');
    }

    const data = await res.json();
    if (data.tokens?.accessToken) {
      setAccessToken(data.tokens.accessToken);
      if (data.tokens.refreshToken) {
        setRefreshToken(data.tokens.refreshToken);
      }
      return data.tokens.accessToken;
    } else {
      throw new Error('Invalid refresh payload');
    }
  } catch {
    if (failClosedOnError) {
      failClosed();
    }
    return null;
  }
}

export async function apiFetch(endpoint: string, options: RequestInit = {}): Promise<any> {
  let token = getAccessToken();
  const apiBase = resolveApiBase();
  const isSameOrigin = apiBase.startsWith('/');

  const executeRequest = async (currentToken: string | null) => {
    return fetch(`${apiBase}${endpoint}`, {
      ...options,
      mode: isSameOrigin ? 'same-origin' : 'cors',
      credentials: 'include',
      headers: buildApiHeaders(currentToken, options),
    });
  };

  let response = await executeRequest(token);

  if (response.status === 401) {
    if (!isRefreshing) {
      isRefreshing = true;
      const newToken = await refreshAccessToken();
      isRefreshing = false;
      onRefreshed(newToken);

      if (newToken) {
        response = await executeRequest(newToken);
      } else {
        throw new Error('Unauthorized');
      }
    } else {
      const newToken = await new Promise<string | null>(resolve => {
        addRefreshSubscriber(tok => resolve(tok));
      });

      if (newToken) {
        response = await executeRequest(newToken);
      } else {
        throw new Error('Unauthorized');
      }
    }
  }

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.message || errorData?.error || `Request failed with status ${response.status}`);
  }

  // Handle empty responses like 204 No Content
  const text = await response.text();
  if (!text) return {};

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
