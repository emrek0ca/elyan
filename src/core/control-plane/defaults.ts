import { getControlPlanePlan } from './catalog';
import { createUsageSnapshot } from './usage';
import {
  controlPlaneBillingPlanBindingSchema,
  controlPlaneBillingStateSchema,
  controlPlanePlanIdSchema,
  controlPlaneStateSchema,
  controlPlaneStateV4Schema,
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
    version: 4,
    billing,
    users: {},
    accounts: {},
    ledger: [],
    notifications: [],
    devices: {},
    deviceLinks: {},
    evaluationSignals: [],
  };
}

export function migrateControlPlaneState(rawState: unknown): ControlPlaneState {
  const parsed = controlPlaneStateSchema.parse(rawState);

  if (parsed.version === 4) {
    return parsed;
  }

  return controlPlaneStateV4Schema.parse({
    version: 4,
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
          },
        ];
      })
    ),
    ledger: parsed.ledger,
    notifications: 'notifications' in parsed ? parsed.notifications : [],
    devices: 'devices' in parsed ? parsed.devices : {},
    deviceLinks: 'deviceLinks' in parsed ? parsed.deviceLinks : {},
    evaluationSignals: 'evaluationSignals' in parsed ? parsed.evaluationSignals : [],
  });
}
