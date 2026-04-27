import { NextRequest, NextResponse } from 'next/server';
import { createOperatorRunInputSchema, getOperatorRunStore } from '@/core/operator';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

export async function GET() {
  const runs = await getOperatorRunStore().list();

  return NextResponse.json({
    ok: true,
    runs,
  });
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => null);
  const parsed = createOperatorRunInputSchema.safeParse(body);

  if (!parsed.success) {
    return NextResponse.json(
      {
        ok: false,
        error: 'Invalid operator run request.',
        issues: parsed.error.flatten().fieldErrors,
      },
      { status: 400 }
    );
  }

  const run = await getOperatorRunStore().create(parsed.data);

  return NextResponse.json(
    {
      ok: true,
      run,
    },
    { status: 201 }
  );
}

