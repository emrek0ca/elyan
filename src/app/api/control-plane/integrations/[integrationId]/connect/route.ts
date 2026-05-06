import { randomBytes, randomUUID } from 'crypto';
import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { getControlPlaneService } from '@/core/control-plane';
import { buildIntegrationAuthorizationContext, isIntegrationProviderConfigured } from '@/core/control-plane/integration-provider';
import { requireControlPlaneSession } from '@/core/control-plane/session';
import { env } from '@/lib/env';
import { encryptIntegrationSecret } from '@/core/control-plane/integration-provider';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const providerParamsSchema = z.object({
  integrationId: z.enum(['google', 'github', 'notion']),
});

function sanitizeReturnTo(value: string | null) {
  if (!value || !value.startsWith('/')) {
    return '/manage#manage-integrations';
  }

  return value;
}

function isSecureCookie() {
  return Boolean(env.NEXTAUTH_URL?.startsWith('https://'));
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ integrationId: string }> }
) {
  try {
    const params = providerParamsSchema.safeParse(await context.params);
    if (!params.success) {
      return NextResponse.json(
        { ok: false, error: 'Invalid integration provider', issues: params.error.flatten().fieldErrors },
        { status: 400 }
      );
    }

    const provider = params.data.integrationId;
    if (!isIntegrationProviderConfigured(provider)) {
      return NextResponse.json(
        { ok: false, error: `${provider} OAuth is not configured` },
        { status: 503 }
      );
    }

    const session = await requireControlPlaneSession(request);
    const returnTo = sanitizeReturnTo(request.nextUrl.searchParams.get('returnTo'));
    const state = randomUUID().replace(/-/g, '');
    const codeVerifier = randomBytes(32).toString('base64url');
    const contextData = buildIntegrationAuthorizationContext(provider, {
      accountId: session.accountId!,
      userId: session.sub!,
      returnTo,
      state,
      codeVerifier,
    });

    await getControlPlaneService().beginIntegrationConnection(session.accountId!, session.sub!, {
      provider,
      returnTo,
      authorizationUrl: contextData.authorizationUrl,
      state,
    });

    const payload = encryptIntegrationSecret(
      JSON.stringify({
        provider,
        accountId: session.accountId,
        userId: session.sub,
        returnTo,
        state,
        codeVerifier,
        createdAt: new Date().toISOString(),
      })
    );

    const response = NextResponse.redirect(contextData.authorizationUrl);
    response.cookies.set('elyan.integration.oauth', payload, {
      httpOnly: true,
      sameSite: 'lax',
      secure: isSecureCookie(),
      path: '/',
      maxAge: 10 * 60,
    });
    return response;
  } catch (error: unknown) {
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number((error as { statusCode: number }).statusCode) || 500
        : 500;
    const message = error instanceof Error ? error.message : 'integration connect start failed';
    return NextResponse.json({ ok: false, error: message }, { status });
  }
}
