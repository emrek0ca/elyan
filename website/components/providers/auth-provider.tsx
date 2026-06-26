"use client";

import React, { createContext, useContext, useEffect, useRef, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { apiFetch, clearTokens, getAccessToken, refreshAccessToken, setAccessToken, setRefreshToken } from '@/lib/api-client';

export type User = {
  id: string;
  email: string;
  displayName?: string;
  hasAvatar?: boolean;
  avatarVersion?: number;
};

type AuthState = 'unauthenticated' | 'authenticating' | 'authenticated';

interface AuthContextValue {
  state: AuthState;
  user: User | null;
  completeAuth: (data: any) => void;
  login: (data: any) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  state: 'authenticating',
  user: null,
  completeAuth: () => {},
  login: async () => {},
  logout: async () => {},
});

function getLocaleFromPath(pathname: string): string {
  if (pathname.startsWith('/en')) return 'en';
  return 'tr';
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>('authenticating');
  const [user, setUser] = useState<User | null>(null);
  const authEpochRef = useRef(0);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Fail-closed: any 401/auth failure flushes state to unauthenticated.
    // We do NOT unconditionally redirect here because public pages (homepage, /privacy, etc.)
    // should remain accessible even when logged out. Protected pages (like /app/chat)
    // must check state === 'unauthenticated' and redirect themselves.
    const onFailClosed = () => {
      setState('unauthenticated');
      setUser(null);
    };
    window.addEventListener('auth_fail_closed', onFailClosed);
    return () => window.removeEventListener('auth_fail_closed', onFailClosed);
  }, [router, pathname]);

  useEffect(() => {
    const init = async () => {
      const epoch = authEpochRef.current;
      try {
        let token = getAccessToken();
        if (!token) {
          // Attempt silent refresh from stored refreshToken
          token = await refreshAccessToken({ failClosedOnError: false });
        }

        if (epoch !== authEpochRef.current) {
          return;
        }

        if (token) {
          const data = await apiFetch('/v1/auth/me');
          if (epoch !== authEpochRef.current) {
            return;
          }
          setUser(data.user || data);
          setState('authenticated');
        } else {
          clearTokens();
          setState('unauthenticated');
        }
      } catch {
        if (epoch !== authEpochRef.current) {
          return;
        }
        setState('unauthenticated');
        clearTokens();
      }
    };
    init();
  }, []);

  const completeAuth = (payload: any) => {
    const tokens = payload?.tokens || payload?.token || payload;
    const accessToken = tokens?.accessToken || tokens?.access_token;
    const refreshToken = tokens?.refreshToken || tokens?.refresh_token || null;

    if (!accessToken) {
      throw new Error('Access token alınamadı');
    }

    authEpochRef.current += 1;
    setAccessToken(accessToken);
    setRefreshToken(refreshToken);
    setUser(payload?.user || tokens?.user || null);
    setState('authenticated');
    router.replace(`/${getLocaleFromPath(pathname)}/app/chat`);
  };

  const login = async (payload: any) => {
    setState('authenticating');
    try {
      const data = await apiFetch('/v1/auth/login', {
        method: 'POST',
        body: JSON.stringify(payload)
      });
      completeAuth(data);
    } catch (e) {
      setState('unauthenticated');
      throw e;
    }
  };

  const logout = async () => {
    const locale = getLocaleFromPath(pathname);
    try {
      if (getAccessToken()) {
        await apiFetch('/v1/auth/logout', { method: 'POST' }).catch(() => {});
      }
    } finally {
      clearTokens();
      setState('unauthenticated');
      setUser(null);
      router.replace(`/${locale}/app/login`);
    }
  };

  return (
    <AuthContext.Provider value={{ state, user, completeAuth, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
