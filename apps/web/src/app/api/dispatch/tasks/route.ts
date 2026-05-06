import { NextRequest, NextResponse } from 'next/server';
import { dispatchTaskRequestSchema } from '@/core/dispatch';
import { getDispatchStatus, listDispatchTasks, submitDispatchTask } from '@/core/dispatch';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';
import { resolveDispatchSession } from '@/core/dispatch/auth';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET(request: NextRequest) {
  try {
    const session = await resolveDispatchSession(request);
    const [tasks, snapshot] = await Promise.all([listDispatchTasks(), getDispatchStatus()]);
    return NextResponse.json({
      ok: true,
      tasks,
      snapshot,
      session: session
        ? {
            accountId: session.accountId,
            email: session.email,
            name: session.name,
            role: session.role,
          }
        : null,
    });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'dispatch_list_failed',
      message: 'Dispatch task list request failed',
    });
    return createApiErrorResponse(normalized);
  }
}

export async function POST(request: NextRequest) {
  try {
    const session = await resolveDispatchSession(request);
    const body = await request.json().catch(() => null);
    const parsed = dispatchTaskRequestSchema.safeParse(body);

    if (!parsed.success) {
      return createApiErrorResponse({
        status: 400,
        code: 'invalid_dispatch_request',
        message: 'Dispatch request body does not match the expected schema.',
        issues: parsed.error.flatten().fieldErrors,
      });
    }

    const task = await submitDispatchTask(
      parsed.data,
      session
        ? {
            accountId: session.accountId,
            spaceId: session.accountId,
            controlPlaneSession: session,
          }
        : {}
    );

    return NextResponse.json(
      {
        ok: true,
        task,
      },
      { status: 201 }
    );
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'dispatch_create_failed',
      message: 'Dispatch task creation failed',
    });
    return createApiErrorResponse(normalized);
  }
}
