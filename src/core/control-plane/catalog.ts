import { controlPlanePlanSchema, type ControlPlanePlan, type ControlPlanePlanId } from './types';

function createPlanDefinition(plan: ControlPlanePlan): ControlPlanePlan {
  return controlPlanePlanSchema.parse(plan);
}

export const controlPlanePlanCatalog: ControlPlanePlan[] = [
  createPlanDefinition({
    id: 'local_byok',
    title: 'Local / BYOK',
    summary: 'Private local runtime with user-owned keys and no hosted credit requirement.',
    audience: 'Privacy-first individuals who want the local agent runtime only.',
    monthlyPriceTRY: '0.00',
    monthlyIncludedCredits: '0.00',
    entitlements: {
      hostedAccess: false,
      hostedUsageAccounting: false,
      managedCredits: false,
      cloudRouting: false,
      advancedRouting: false,
      teamGovernance: false,
      hostedImprovementSignals: false,
    },
    rateCard: {
      inference: '0.00',
      retrieval: '0.00',
      integrations: '0.00',
      evaluation: '0.00',
    },
    rateLimits: {
      hostedRequestsPerMinute: 0,
      hostedToolCallsPerMinute: 0,
    },
    upgradeTriggers: [
      'User wants hosted access',
      'User wants managed credits',
      'User wants shared billing or account services',
    ],
  }),
  createPlanDefinition({
    id: 'cloud_assisted',
    title: 'Cloud-Assisted',
    summary: 'Managed hosted access with included credits and a simple upgrade path from local-first usage.',
    audience: 'Users who want elyan.dev access and managed hosted credits.',
    monthlyPriceTRY: '399.00',
    monthlyIncludedCredits: '1000.00',
    entitlements: {
      hostedAccess: true,
      hostedUsageAccounting: true,
      managedCredits: true,
      cloudRouting: true,
      advancedRouting: true,
      teamGovernance: false,
      hostedImprovementSignals: true,
    },
    rateCard: {
      inference: '1.00',
      retrieval: '0.10',
      integrations: '0.50',
      evaluation: '0.25',
    },
    rateLimits: {
      hostedRequestsPerMinute: 30,
      hostedToolCallsPerMinute: 10,
    },
    upgradeTriggers: [
      'Hosted credit balance is consistently consumed',
      'User needs higher throughput or better routing',
      'User wants more advanced hosted capabilities',
    ],
  }),
  createPlanDefinition({
    id: 'pro_builder',
    title: 'Pro / Builder',
    summary: 'Higher-hosted-credit plan for power users and heavier multi-LLM workflows.',
    audience: 'Power users, builders, and heavier hosted usage.',
    monthlyPriceTRY: '999.00',
    monthlyIncludedCredits: '5000.00',
    entitlements: {
      hostedAccess: true,
      hostedUsageAccounting: true,
      managedCredits: true,
      cloudRouting: true,
      advancedRouting: true,
      teamGovernance: false,
      hostedImprovementSignals: true,
    },
    rateCard: {
      inference: '0.95',
      retrieval: '0.09',
      integrations: '0.45',
      evaluation: '0.20',
    },
    rateLimits: {
      hostedRequestsPerMinute: 120,
      hostedToolCallsPerMinute: 30,
    },
    upgradeTriggers: [
      'Hosted request rate is growing',
      'User needs more credits or lower effective cost',
      'User wants more aggressive multi-LLM routing',
    ],
  }),
  createPlanDefinition({
    id: 'team_business',
    title: 'Team / Business',
    summary: 'Team-ready hosted plan with governance, shared billing, and higher limits.',
    audience: 'Small teams and business deployments.',
    monthlyPriceTRY: '2499.00',
    monthlyIncludedCredits: '10000.00',
    entitlements: {
      hostedAccess: true,
      hostedUsageAccounting: true,
      managedCredits: true,
      cloudRouting: true,
      advancedRouting: true,
      teamGovernance: true,
      hostedImprovementSignals: true,
    },
    rateCard: {
      inference: '0.90',
      retrieval: '0.08',
      integrations: '0.40',
      evaluation: '0.20',
    },
    rateLimits: {
      hostedRequestsPerMinute: 300,
      hostedToolCallsPerMinute: 80,
    },
    upgradeTriggers: [
      'Multiple users need shared billing',
      'Admin controls are required',
      'Hosted access needs governance and policy controls',
    ],
  }),
];

export function getControlPlanePlan(planId: ControlPlanePlanId): ControlPlanePlan {
  const plan = controlPlanePlanCatalog.find((entry) => entry.id === planId);
  if (!plan) {
    throw new Error(`Unknown control-plane plan: ${planId}`);
  }

  return plan;
}
