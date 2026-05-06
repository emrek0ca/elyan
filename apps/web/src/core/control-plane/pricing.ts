import Decimal from 'decimal.js';
import type { OrchestrationPlan } from '@/core/orchestration';
import type { ControlPlanePlan, ControlPlaneUsageInput } from './types';
import type { UsageBudget } from '@/core/orchestration/types';

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

function toTokenEstimate(value: Decimal.Value) {
  return Math.max(0, Math.round(new Decimal(value).toNumber()));
}

const DEFAULT_USAGE_BUDGET: UsageBudget = {
  inference: 0,
  retrieval: 0,
  integrations: 0,
  evaluation: 0,
};

function resolveUsageBudget(plan: OrchestrationPlan): UsageBudget {
  return plan.usageBudget ?? DEFAULT_USAGE_BUDGET;
}

export function estimateHostedUsageDraft(
  plan: OrchestrationPlan,
  requestId?: string
): ControlPlaneUsageInput[] {
  const usageBudget = resolveUsageBudget(plan);
  const usage: ControlPlaneUsageInput[] = [
    {
      domain: 'inference',
      units: usageBudget.inference,
      tokens: toTokenEstimate(new Decimal(usageBudget.inference).mul(1200)),
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:inference`,
    },
    {
      domain: 'retrieval',
      units: usageBudget.retrieval,
      tokens: toTokenEstimate(new Decimal(usageBudget.retrieval).mul(750)),
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:retrieval`,
    },
  ];

  if (usageBudget.integrations > 0) {
    usage.push({
      domain: 'integrations',
      units: toFixedUnits(usageBudget.integrations),
      tokens: toTokenEstimate(new Decimal(usageBudget.integrations).mul(500)),
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:integrations`,
    });
  }

  if (usageBudget.evaluation > 0) {
    usage.push({
      domain: 'evaluation',
      units: toFixedUnits(usageBudget.evaluation),
      tokens: toTokenEstimate(new Decimal(usageBudget.evaluation).mul(350)),
      source: 'hosted_web',
      requestId,
      note: `${plan.mode}:${plan.reasoningDepth}:${plan.taskIntent}:evaluation`,
    });
  }

  return usage;
}

export function estimateHostedRequestTokens(plan: OrchestrationPlan) {
  return estimateHostedUsageDraft(plan).reduce((total, input) => total + Math.max(0, Math.round(input.tokens ?? 0)), 0);
}

export function estimateRunCostUsd(input: {
  modelId: string;
  tokens: number;
  stepBudget: number;
  retryLimit: number;
}) {
  const localModel =
    /^(ollama:|local:|lmstudio:|llama\.cpp:|openai:gpt-oss|anthropic:.*local)/i.test(input.modelId) ||
    /\b(local|ollama|lmstudio|llama)\b/i.test(input.modelId);
  const tokenRate = localModel ? 0.0000025 : 0.00001;
  const stepRate = localModel ? 0.001 : 0.002;
  const retryRate = localModel ? 0.0015 : 0.003;

  return Number(
    (
      Math.max(0, input.tokens) * tokenRate +
      Math.max(0, input.stepBudget) * stepRate +
      Math.max(0, input.retryLimit) * retryRate +
      (localModel ? 0.0005 : 0.003)
    ).toFixed(4)
  );
}
