import { NextRequest, NextResponse } from 'next/server';
import { z } from 'zod';
import { getControlPlaneService } from '@/core/control-plane';
import {
  decryptIntegrationSecret,
  isIntegrationProviderConfigured,
} from '@/core/control-plane/integration-provider';
import { requireControlPlaneSession } from '@/core/control-plane/session';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const providerParamsSchema = z.object({
  integrationId: z.enum(['google', 'github', 'notion']),
});

function sanitizeReturnTo(value: string | undefined) {
  if (!value || !value.startsWith('/')) {
    return '/manage#manage-integrations';
  }

  return value;
}

function buildRedirectUrl(request: NextRequest, returnTo: string, provider: string, status: string, error?: string) {
  const url = new URL(sanitizeReturnTo(returnTo), request.url);
  url.searchParams.set('integration', provider);
  url.searchParams.set('status', status);
  if (error) {
    url.searchParams.set('error', error);
  }
  return url;
}

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ integrationId: string }> }
) {
  const clearCookie = (response: NextResponse) => {
    response.cookies.set('elyan.integration.oauth', '', {
      httpOnly: true,
      sameSite: 'lax',
      path: '/',
      maxAge: 0,
    });
    return response;
  };

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
      return NextResponse.json({ ok: false, error: `${provider} OAuth is not configured` }, { status: 503 });
    }

    const session = await requireControlPlaneSession(request);
    const cookie = request.cookies.get('elyan.integration.oauth')?.value;
    if (!cookie) {
      return clearCookie(
        NextResponse.redirect(buildRedirectUrl(request, '/manage#manage-integrations', provider, 'error', 'missing_state'))
      );
    }

    const decoded = JSON.parse(decryptIntegrationSecret(cookie)) as {
      provider?: string;
      accountId?: string;
      userId?: string;
      returnTo?: string;
      state?: string;
      codeVerifier?: string;
    };

    if (
      decoded.provider !== provider ||
      decoded.accountId !== session.accountId ||
      decoded.userId !== session.sub
    ) {
      return clearCookie(
        NextResponse.redirect(
          buildRedirectUrl(request, decoded.returnTo ?? '/manage#manage-integrations', provider, 'error', 'state_mismatch')
        )
      );
    }

    const code = request.nextUrl.searchParams.get('code');
    const state = request.nextUrl.searchParams.get('state');
    if (!code || !state || state !== decoded.state) {
      return clearCookie(
        NextResponse.redirect(
          buildRedirectUrl(
            request,
            decoded.returnTo ?? '/manage#manage-integrations',
            provider,
            'error',
            'invalid_callback'
          )
        )
      );
    }

    if (!decoded.codeVerifier) {
      return clearCookie(
        NextResponse.redirect(
          buildRedirectUrl(
            request,
            decoded.returnTo ?? '/manage#manage-integrations',
            provider,
            'error',
            'missing_code_verifier'
          )
        )
      );
    }

    await getControlPlaneService().completeIntegrationConnection({
      provider,
      accountId: session.accountId!,
      userId: session.sub!,
      code,
      state,
      codeVerifier: decoded.codeVerifier,
      returnTo: decoded.returnTo,
    });

    return clearCookie(
      NextResponse.redirect(
        buildRedirectUrl(request, decoded.returnTo ?? '/manage#manage-integrations', provider, 'connected')
      )
    );
  } catch (error: unknown) {
    const provider = request.nextUrl.pathname.split('/').at(-2) ?? 'unknown';
    const status =
      error && typeof error === 'object' && 'statusCode' in error
        ? Number((error as { statusCode: number }).statusCode) || 500
        : 500;
    const message = error instanceof Error ? error.message : 'integration callback failed';
    return NextResponse.json({ ok: false, error: message, provider }, { status });
  }
}
