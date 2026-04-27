import { describe, expect, it } from 'vitest';
import { isIyzicoSubscriptionAddonUnavailable } from '@/core/control-plane/iyzico';

describe('iyzico provider classification', () => {
  it('recognizes the subscription add-on unavailable sandbox failure', () => {
    expect(
      isIyzicoSubscriptionAddonUnavailable(
        {
          status: 'failure',
          errorCode: '100001',
          errorMessage: 'Sistem hatası',
        },
        422
      )
    ).toBe(true);
  });

  it('does not misclassify unrelated provider failures', () => {
    expect(
      isIyzicoSubscriptionAddonUnavailable(
        {
          status: 'failure',
          errorCode: '100001',
          errorMessage: 'Different error',
        },
        422
      )
    ).toBe(false);

    expect(
      isIyzicoSubscriptionAddonUnavailable(
        {
          status: 'failure',
          errorCode: '200001',
          errorMessage: 'Sistem hatası',
        },
        422
      )
    ).toBe(false);
  });
});
