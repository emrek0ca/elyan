import { NextResponse } from 'next/server';
import { registry } from '@/core/providers';

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Failed to list models';
}

export async function GET() {
  try {
    const models = await registry.listAvailableModels();
    return NextResponse.json({ models });
  } catch (error: unknown) {
    console.error('Models endpoint error:', error);
    return NextResponse.json({ error: getErrorMessage(error) }, { status: 500 });
  }
}
