import { getControlPlanePlan } from './catalog';
import {
  controlPlaneBillingPlanBindingSchema,
  controlPlaneBillingStateSchema,
  controlPlanePlanIdSchema,
  controlPlaneStateSchema,
  controlPlaneStateV3Schema,
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
      version: 3,
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

  if (parsed.version === 3) {
    return parsed;
  }

  return controlPlaneStateV3Schema.parse({
    version: 3,
    billing: createDefaultControlPlaneState().billing,
    users: {},
    accounts: parsed.accounts,
    ledger: parsed.ledger,
    notifications: [],
    devices: {},
    deviceLinks: {},
    evaluationSignals: [],
  });
}
