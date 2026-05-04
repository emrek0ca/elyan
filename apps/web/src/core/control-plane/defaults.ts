import { getControlPlanePlan } from './catalog';
import { createUsageSnapshot } from './usage';
import {
  controlPlaneBillingPlanBindingSchema,
  controlPlaneBillingStateSchema,
  controlPlanePlanIdSchema,
  controlPlaneStateSchema,
  controlPlaneStateV6Schema,
  type ControlPlaneState,
} from './types';

export function createDefaultControlPlaneState(): ControlPlaneState {
  const billing = controlPlaneBillingStateSchema.parse({
    iyzico: {
      plans: Object.fromEntries(
        controlPlanePlanIdSchema.options.map((planId) => [
          planId,
          (() => {
            const plan = getControlPlanePlan(planId);
            return controlPlaneBillingPlanBindingSchema.parse({
              provider: 'iyzico',
              planId,
              productName: `Elyan ${plan.title}`,
              pricingPlanName: `${plan.title} Monthly`,
              currencyCode: 'TRY',
              paymentInterval: 'MONTHLY',
              paymentIntervalCount: 1,
              planPaymentType: 'RECURRING',
              syncState: 'unbound',
            });
          })(),
        ])
      ),
    },
  });

  return {
    version: 6,
    billing,
    users: {},
    accounts: {},
    ledger: [],
    notifications: [],
    devices: {},
    deviceLinks: {},
    evaluationSignals: [],
    learningEvents: [],
  };
}

export function migrateControlPlaneState(rawState: unknown): ControlPlaneState {
  const parsed = controlPlaneStateSchema.parse(rawState);

  if (parsed.version === 6) {
    return parsed;
  }

  return controlPlaneStateV6Schema.parse({
    version: 6,
    billing: createDefaultControlPlaneState().billing,
    users: 'users' in parsed ? parsed.users : {},
    accounts: Object.fromEntries(
      Object.entries(parsed.accounts).map(([accountId, account]) => {
        const legacyAccount = account as {
          subscription: {
            planId: Parameters<typeof getControlPlanePlan>[0];
          };
          balanceCredits: string;
          usageSnapshot?: ControlPlaneState['accounts'][string]['usageSnapshot'];
        };
        const plan = getControlPlanePlan(legacyAccount.subscription.planId);
        return [
          accountId,
          {
            ...legacyAccount,
            usageSnapshot:
            legacyAccount.usageSnapshot ??
            createUsageSnapshot(plan, legacyAccount.balanceCredits, new Date(), {
              dailyRequests: 0,
              dailyHostedToolActionCalls: 0,
            }),
          integrations:
            'integrations' in legacyAccount && legacyAccount.integrations
              ? legacyAccount.integrations
              : {},
          interactionState:
            'interactionState' in legacyAccount && legacyAccount.interactionState
              ? legacyAccount.interactionState
              : {
                  threads: [],
                    messages: [],
                    memoryItems: [],
                    learningDrafts: [],
                  },
          },
        ];
      })
    ),
    ledger: parsed.ledger,
    notifications: 'notifications' in parsed ? parsed.notifications : [],
    devices: 'devices' in parsed ? parsed.devices : {},
    deviceLinks: 'deviceLinks' in parsed ? parsed.deviceLinks : {},
    evaluationSignals: 'evaluationSignals' in parsed ? parsed.evaluationSignals : [],
    learningEvents: 'learningEvents' in parsed ? parsed.learningEvents : [],
  });
}
