import { createHmac, randomUUID } from 'crypto';
import { z } from 'zod';
import { env } from '@/lib/env';
import { ControlPlaneConfigurationError, ControlPlaneProviderError } from './errors';
import type { ControlPlaneBillingPlanBinding, ControlPlanePlan } from './types';

type IyzicoJson = Record<string, unknown>;

type IyzicoRequestOptions = {
  method: 'GET' | 'POST' | 'DELETE';
  path: string;
  body?: IyzicoJson;
};

export type IyzicoSubscriptionInitResult = {
  token?: string;
  checkoutFormContent?: string;
  paymentPageUrl?: string;
  raw: IyzicoJson;
};

export type IyzicoSubscriptionCustomer = {
  name: string;
  surname: string;
  email: string;
};

export type IyzicoSubscriptionWebhook = {
  orderReferenceCode: string;
  customerReferenceCode: string;
  subscriptionReferenceCode: string;
  iyziReferenceCode: string;
  iyziEventType: 'subscription.order.success' | 'subscription.order.failure';
  iyziEventTime: number;
};

export const iyzicoSubscriptionWebhookSchema = z.object({
  orderReferenceCode: z.string().min(1),
  customerReferenceCode: z.string().min(1),
  subscriptionReferenceCode: z.string().min(1),
  iyziReferenceCode: z.string().min(1),
  iyziEventType: z.enum(['subscription.order.success', 'subscription.order.failure']),
  iyziEventTime: z.number().int().nonnegative(),
});

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function toJsonRecord(value: unknown): IyzicoJson {
  if (!isRecord(value)) {
    return {};
  }

  return value;
}

function readIyzicoString(record: IyzicoJson, key: string) {
  const value = record[key];
  return typeof value === 'string' && value.trim().length > 0 ? value : undefined;
}

function flattenIyzicoRecords(value: unknown, seen = new Set<unknown>()): IyzicoJson[] {
  if (!value || typeof value !== 'object' || seen.has(value)) {
    return [];
  }

  seen.add(value);

  if (Array.isArray(value)) {
    return value.flatMap((entry) => flattenIyzicoRecords(entry, seen));
  }

  const record = value as IyzicoJson;
  const nested: IyzicoJson[] = [record];

  for (const child of Object.values(record)) {
    nested.push(...flattenIyzicoRecords(child, seen));
  }

  return nested;
}

export function isIyzicoSubscriptionAddonUnavailable(json: IyzicoJson, status: number) {
  const errorCode = readIyzicoString(json, 'errorCode');
  const errorMessage = readIyzicoString(json, 'errorMessage') ?? readIyzicoString(json, 'message');
  const normalizedMessage = errorMessage?.toLowerCase() ?? '';

  return (
    status === 422 &&
    errorCode === '100001' &&
    (normalizedMessage.includes('sistem hatası') || normalizedMessage.includes('system error'))
  );
}

function findNamedRecord(records: IyzicoJson[], name: string) {
  const target = name.trim().toLowerCase();
  return records.find((record) => {
    const candidateName =
      readIyzicoString(record, 'name') ??
      readIyzicoString(record, 'productName') ??
      readIyzicoString(record, 'pricingPlanName');

    return candidateName?.trim().toLowerCase() === target;
  });
}

function generateRandomKey() {
  return `${Date.now()}${randomUUID().replace(/-/g, '')}`;
}

function resolveIyzicoCredentials() {
  const mode = env.IYZICO_ENV;

  if (mode === 'sandbox') {
    return {
      apiKey: env.IYZICO_SANDBOX_API_KEY ?? env.IYZICO_API_KEY,
      secretKey: env.IYZICO_SANDBOX_SECRET_KEY ?? env.IYZICO_SECRET_KEY,
      merchantId: env.IYZICO_SANDBOX_MERCHANT_ID ?? env.IYZICO_MERCHANT_ID,
      baseUrl: env.IYZICO_SANDBOX_API_BASE_URL,
    };
  }

  return {
    apiKey: env.IYZICO_API_KEY,
    secretKey: env.IYZICO_SECRET_KEY,
    merchantId: env.IYZICO_MERCHANT_ID,
    baseUrl: env.IYZICO_BASE_URL,
  };
}

function signRequest(randomKey: string, path: string, body: string) {
  const credentials = resolveIyzicoCredentials();

  if (!credentials.apiKey || !credentials.secretKey) {
    throw new ControlPlaneConfigurationError('Iyzico credentials are required for hosted billing operations');
  }

  const payload = `${randomKey}${path}${body}`;
  const signature = createHmac('sha256', credentials.secretKey).update(payload).digest('hex');
  const authorization = Buffer.from(
    `apiKey:${credentials.apiKey}&randomKey:${randomKey}&signature:${signature}`,
    'utf8'
  ).toString('base64');

  return {
    authorization: `IYZWSv2 ${authorization}`,
    randomKey,
  };
}

export function buildIyzicoPlanBinding(plan: ControlPlanePlan): ControlPlaneBillingPlanBinding {
  return {
    provider: 'iyzico',
    planId: plan.id,
    productName: `Elyan ${plan.title}`,
    pricingPlanName: `${plan.title} Monthly`,
    currencyCode: 'TRY',
    paymentInterval: 'MONTHLY',
    paymentIntervalCount: 1,
    planPaymentType: 'RECURRING',
    syncState: 'unbound',
  };
}

export function getIyzicoWebhookExpectedSignature(
  merchantId: string,
  payload: IyzicoSubscriptionWebhook
) {
  const credentials = resolveIyzicoCredentials();

  if (!credentials.secretKey) {
    throw new ControlPlaneConfigurationError('Iyzico secret key is required to verify webhooks');
  }

  const message = `${merchantId}${payload.iyziEventType}${payload.subscriptionReferenceCode}${payload.orderReferenceCode}${payload.customerReferenceCode}`;
  return createHmac('sha256', credentials.secretKey).update(message).digest('hex');
}

export function verifyIyzicoWebhookSignature(
  merchantId: string,
  payload: IyzicoSubscriptionWebhook,
  signatureHeader?: string | null
) {
  if (!signatureHeader) {
    return false;
  }

  const expected = getIyzicoWebhookExpectedSignature(merchantId, payload);
  return signatureHeader.trim().toLowerCase() === expected.toLowerCase();
}

export class IyzicoBillingClient {
  constructor(
    private readonly baseUrl = resolveIyzicoCredentials().baseUrl,
    private readonly merchantId = resolveIyzicoCredentials().merchantId
  ) {}

  isConfigured() {
    const credentials = resolveIyzicoCredentials();
    return Boolean(credentials.apiKey && credentials.secretKey);
  }

  private async request<T>({ method, path, body }: IyzicoRequestOptions): Promise<T> {
    if (!this.isConfigured()) {
      throw new ControlPlaneConfigurationError('Iyzico API credentials are not configured');
    }

    const url = new URL(path, this.baseUrl);
    const payload = body ? JSON.stringify(body) : '';
    const { authorization, randomKey } = signRequest(
      generateRandomKey(),
      url.pathname,
      payload
    );

    const response = await fetch(url, {
      method,
      headers: {
        Authorization: authorization,
        'Content-Type': 'application/json',
        'x-iyzi-rnd': randomKey,
      },
      body: body ? payload : undefined,
    });

    const text = await response.text();
    let parsed: unknown = {};

    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        throw new ControlPlaneProviderError(
          `Iyzico returned an invalid JSON response for ${method} ${url.pathname}`
        );
      }
    }

    const json = toJsonRecord(parsed);

    if (!response.ok || json.status === 'failure') {
      if (isIyzicoSubscriptionAddonUnavailable(json, response.status)) {
        throw new ControlPlaneConfigurationError(
          'Iyzico subscription API is unavailable for this sandbox merchant account. The merchant subscription add-on is not enabled or the sandbox account is not provisioned for subscriptions.'
        );
      }

      const message =
        (typeof json.errorMessage === 'string' ? json.errorMessage : undefined) ??
        (typeof json.message === 'string' ? json.message : undefined) ??
        `Iyzico request failed for ${method} ${url.pathname}`;
      throw new ControlPlaneProviderError(message);
    }

    return json as T;
  }

  async ensureProduct(plan: ControlPlanePlan) {
    const payload = {
      locale: 'en',
      conversationId: `elyan-${plan.id}-product`,
      name: `Elyan ${plan.title}`,
      description: plan.summary,
    };

    const response = await this.request<IyzicoJson>({
      method: 'POST',
      path: '/v2/subscription/products',
      body: payload,
    });

    return {
      raw: response,
      productReferenceCode:
        (typeof response.productReferenceCode === 'string' && response.productReferenceCode) ||
        (typeof response.referenceCode === 'string' && response.referenceCode) ||
        (typeof response.data === 'object' && response.data && 'referenceCode' in response.data
          ? String((response.data as Record<string, unknown>).referenceCode ?? '')
          : ''),
    };
  }

  async listProducts() {
    const response = await this.request<IyzicoJson>({
      method: 'GET',
      path: '/v2/subscription/products',
    });

    return {
      raw: response,
      records: flattenIyzicoRecords(response),
    };
  }

  async listPricingPlans(productReferenceCode: string) {
    const response = await this.request<IyzicoJson>({
      method: 'GET',
      path: `/v2/subscription/products/${productReferenceCode}/pricing-plans`,
    });

    return {
      raw: response,
      records: flattenIyzicoRecords(response),
    };
  }

  async ensurePricingPlan(plan: ControlPlanePlan, productReferenceCode: string) {
    const payload = {
      locale: 'en',
      conversationId: `elyan-${plan.id}-pricing-plan`,
      name: `${plan.title} Monthly`,
      price: Number(plan.monthlyPriceTRY) > 0 ? Number(plan.monthlyPriceTRY) : 1,
      currencyCode: 'TRY',
      paymentInterval: 'MONTHLY',
      paymentIntervalCount: 1,
      planPaymentType: 'RECURRING',
    };

    const response = await this.request<IyzicoJson>({
      method: 'POST',
      path: `/v2/subscription/products/${productReferenceCode}/pricing-plans`,
      body: payload,
    });

    return {
      raw: response,
      pricingPlanReferenceCode:
        (typeof response.pricingPlanReferenceCode === 'string' &&
          response.pricingPlanReferenceCode) ||
        (typeof response.referenceCode === 'string' && response.referenceCode) ||
        (typeof response.data === 'object' && response.data && 'referenceCode' in response.data
          ? String((response.data as Record<string, unknown>).referenceCode ?? '')
          : ''),
    };
  }

  async initializeSubscription(input: {
    plan: ControlPlanePlan;
    pricingPlanReferenceCode: string;
    callbackUrl: string;
    customer: IyzicoSubscriptionCustomer;
    conversationId?: string;
  }): Promise<IyzicoSubscriptionInitResult> {
    const response = await this.request<IyzicoJson>({
      method: 'POST',
      path: '/v2/subscription/checkoutform/initialize',
      body: {
        locale: 'en',
        callbackUrl: input.callbackUrl,
        pricingPlanReferenceCode: input.pricingPlanReferenceCode,
        subscriptionInitialStatus: 'ACTIVE',
        customer: input.customer,
        conversationId: input.conversationId ?? `elyan-${input.plan.id}-${randomUUID()}`,
      },
    });

    return {
      token:
        (typeof response.token === 'string' && response.token) ||
        (typeof response.data === 'object' && response.data && 'token' in response.data
          ? String((response.data as Record<string, unknown>).token ?? '')
          : undefined),
      checkoutFormContent:
        (typeof response.checkoutFormContent === 'string' && response.checkoutFormContent) ||
        (typeof response.data === 'object' && response.data && 'checkoutFormContent' in response.data
          ? String((response.data as Record<string, unknown>).checkoutFormContent ?? '')
          : undefined),
      paymentPageUrl:
        (typeof response.paymentPageUrl === 'string' && response.paymentPageUrl) ||
        (typeof response.data === 'object' && response.data && 'paymentPageUrl' in response.data
          ? String((response.data as Record<string, unknown>).paymentPageUrl ?? '')
          : undefined),
      raw: response,
    };
  }

  async updateCustomer(customerReferenceCode: string, body: IyzicoJson) {
    return this.request<IyzicoJson>({
      method: 'POST',
      path: `/v2/subscription/customers/${customerReferenceCode}`,
      body,
    });
  }

  verifyWebhook(payload: IyzicoSubscriptionWebhook, signatureHeader?: string | null) {
    if (!this.merchantId) {
      throw new ControlPlaneConfigurationError('Iyzico merchant id is required to verify webhooks');
    }

    return verifyIyzicoWebhookSignature(this.merchantId, payload, signatureHeader);
  }

  async findProductReferenceCodeByName(productName: string) {
    const response = await this.listProducts();
    const match = findNamedRecord(response.records, productName);

    return (
      readIyzicoString(match ?? {}, 'productReferenceCode') ??
      readIyzicoString(match ?? {}, 'referenceCode') ??
      readIyzicoString(match ?? {}, 'id')
    );
  }

  async findPricingPlanReferenceCodeByName(productReferenceCode: string, pricingPlanName: string) {
    const response = await this.listPricingPlans(productReferenceCode);
    const match = findNamedRecord(response.records, pricingPlanName);

    return (
      readIyzicoString(match ?? {}, 'pricingPlanReferenceCode') ??
      readIyzicoString(match ?? {}, 'referenceCode') ??
      readIyzicoString(match ?? {}, 'id')
    );
  }
}

export function getIyzicoBillingClient() {
  return new IyzicoBillingClient();
}
