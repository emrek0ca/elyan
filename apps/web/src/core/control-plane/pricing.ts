import Decimal from 'decimal.js';
import type { OrchestrationPlan } from '@/core/orchestration';
import type { ControlPlanePlan, ControlPlaneUsageInput } from './types';

export type ControlPlanePlanPricingView = {
  id: ControlPlanePlan['id'];
  tier: ControlPlanePlan['tier'];
  title: ControlPlanePlan['title'];
  summary: ControlPlanePlan['summary'];
  audience: ControlPlanePlan['audience'];
  billingSurface: 'local' | 'hosted';
  monthlyPriceTRY: string;
  monthlyIncludedCredits: string;
  tokenLimits: ControlPlanePlan['tokenLimits'];
  modelAccess: ControlPlanePlan['modelAccess'];
  featureAccess: ControlPlanePlan['featureAccess'];
  usageBuckets: ControlPlanePlan['rateCard'];
  rateLimits: ControlPlanePlan['rateLimits'];
  dailyLimits: ControlPlanePlan['dailyLimits'];
  upgradeTriggers: ControlPlanePlan['upgradeTriggers'];
  pricingNarrative: string;
};

export function buildPlanPricingView(plan: ControlPlanePlan): ControlPlanePlanPricingView {
  const billingSurface: ControlPlanePlanPricingView['billingSurface'] = plan.entitlements.hostedAccess
    ? 'hosted'
    : 'local';

  return {
    id: plan.id,
    tier: plan.tier,
    title: plan.title,
    summary: plan.summary,
    audience: plan.audience,
    billingSurface,
    monthlyPriceTRY: plan.monthlyPriceTRY,
    monthlyIncludedCredits: plan.monthlyIncludedCredits,
    tokenLimits: plan.tokenLimits,
    modelAccess: plan.modelAccess,
    featureAccess: plan.featureAccess,
    usageBuckets: plan.rateCard,
    rateLimits: plan.rateLimits,
    dailyLimits: plan.dailyLimits,
    upgradeTriggers: plan.upgradeTriggers,
    pricingNarrative:
      billingSurface === 'local'
        ? 'Local runtime stays free of hosted credit accounting. Bring your own keys or use local models.'
        : 'Hosted usage is metered against included credits with explicit per-domain buckets and daily guardrails.',
  };
}

function toFixedUnits(value: Decimal.Value) {
  return new Decimal(value).toDecimalPlaces(2).toNumber();
}

export function estimateHostedUsageDraft(
  plan: OrchestrationPlan,
  requestId?: string
): ControlPlaneUsageInput[] {
  const usage: ControlPlaneUsageInput[] = [
    {
      domain: 'inference',
      units: plan.usageBudget.inference,
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:inference`,
    },
    {
      domain: 'retrieval',
      units: plan.usageBudget.retrieval,
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:retrieval`,
    },
  ];

  if (plan.usageBudget.integrations > 0) {
    usage.push({
      domain: 'integrations',
      units: toFixedUnits(plan.usageBudget.integrations),
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:integrations`,
    });
  }

  if (plan.usageBudget.evaluation > 0) {
    usage.push({
      domain: 'evaluation',
      units: toFixedUnits(plan.usageBudget.evaluation),
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:evaluation`,
    });
  }

  return usage;
}
