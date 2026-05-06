import { NextRequest, NextResponse } from 'next/server';
import { resumeDispatchTask } from '@/core/dispatch';
import { createApiErrorResponse, normalizeApiError } from '@/core/http/api-errors';
import { resolveDispatchSession } from '@/core/dispatch/auth';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function POST(request: NextRequest, context: { params: Promise<{ taskId: string }> }) {
  try {
    await resolveDispatchSession(request);
    const { taskId } = await context.params;
    const body = await request.json().catch(() => ({}));
    const note = typeof body?.note === 'string' ? body.note : undefined;
    const task = await resumeDispatchTask(taskId, note);

    if (!task) {
      return createApiErrorResponse({
        status: 404,
        code: 'dispatch_task_not_found',
        message: 'Dispatch task not found',
      });
    }

    return NextResponse.json({
      ok: true,
      task,
    });
  } catch (error: unknown) {
    const normalized = normalizeApiError(error, {
      status: 500,
      code: 'dispatch_task_resume_failed',
      message: 'Dispatch task resume failed',
    });
    return createApiErrorResponse(normalized);
  }
}
