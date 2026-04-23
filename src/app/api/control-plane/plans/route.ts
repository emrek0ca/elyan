import { NextResponse } from 'next/server';
import { buildPlanPricingView, getControlPlaneService } from '@/core/control-plane';

export const dynamic = 'force-dynamic';

export async function GET() {
  const plans = await getControlPlaneService().listPlans();
  return NextResponse.json({
    ok: true,
    surface: 'shared-vps',
    plans: plans.map((plan) => ({
      ...plan,
      pricing: buildPlanPricingView(plan),
    })),
  });
}
