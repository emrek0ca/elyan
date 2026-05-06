import type { NextRequest } from 'next/server';
import { isHostedAuthConfigured } from '@/core/control-plane/auth';
import { requireControlPlaneSession, type ControlPlaneSessionToken } from '@/core/control-plane/session';

export async function resolveDispatchSession(request: NextRequest): Promise<ControlPlaneSessionToken | null> {
  if (!isHostedAuthConfigured()) {
    return null;
  }

  return requireControlPlaneSession(request);
}
