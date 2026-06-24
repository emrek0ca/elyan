import { createHmac, randomBytes, randomUUID, timingSafeEqual } from "node:crypto";
import type { AppEnv } from "../../config/env.js";
import { badRequest, conflict, serviceUnavailable, unauthorized } from "../../lib/errors.js";

type IyzicoRequestBody = Record<string, unknown>;

type IyzicoSubscriptionCustomer = {
  name: string;
  surname: string;
  email: string;
  gsmNumber: string;
  identityNumber: string;
  billingAddress: {
    address: string;
    zipCode: string;
    contactName: string;
    city: string;
    country: string;
  };
  shippingAddress: {
    address: string;
    zipCode: string;
    contactName: string;
    city: string;
    country: string;
  };
};

type IyzicoCheckoutInitInput = {
  conversationId: string;
  callbackUrl: string;
  pricingPlanReferenceCode: string;
  customer: IyzicoSubscriptionCustomer;
};

export type IyzicoCatalogPlanInput = {
  planCode: string;
  planName: string;
  monthlyPrice: number;
  currencyCode: "USD";
};

function compactJson(body: IyzicoRequestBody): string {
  return JSON.stringify(body);
}

function normalizeStatus(value: unknown): string {
  return String(value || "").trim().toLowerCase();
}

function compareSignatures(left: string, right: string): boolean {
  const a = Buffer.from(left.trim().toLowerCase());
  const b = Buffer.from(right.trim().toLowerCase());

  if (a.length !== b.length) {
    return false;
  }

  return timingSafeEqual(a, b);
}

function splitName(fullName: string): { name: string; surname: string } {
  const parts = fullName
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (parts.length === 0) {
    return {
      name: "Elyan",
      surname: "Customer",
    };
  }

  if (parts.length === 1) {
    return {
      name: parts[0],
      surname: "Customer",
    };
  }

  return {
    name: parts[0],
    surname: parts.slice(1).join(" "),
  };
}

export function buildIyzicoCustomer(input: {
  fullName: string;
  email: string;
  phone: string;
  identityNumber: string;
  addressLine1: string;
  city: string;
  country: string;
  zipCode: string;
}): IyzicoSubscriptionCustomer {
  const { name, surname } = splitName(input.fullName);
  const address = {
    address: input.addressLine1.trim(),
    zipCode: input.zipCode.trim(),
    contactName: input.fullName.trim(),
    city: input.city.trim(),
    country: input.country.trim(),
  };

  return {
    name,
    surname,
    email: input.email.trim(),
    gsmNumber: input.phone.trim(),
    identityNumber: input.identityNumber.trim(),
    billingAddress: address,
    shippingAddress: address,
  };
}

export class IyzicoClient {
  public constructor(private readonly env: AppEnv) {}

  public assertConfigured(): void {
    const missing = [];

    if (!this.env.IYZICO_API_KEY) {
      missing.push("IYZICO_API_KEY");
    }

    if (!this.env.IYZICO_SECRET_KEY) {
      missing.push("IYZICO_SECRET_KEY");
    }

    if (!this.env.IYZICO_MERCHANT_ID) {
      missing.push("IYZICO_MERCHANT_ID");
    }

    if (missing.length > 0) {
      throw conflict(`iyzico_config_missing:${missing.join(",")}`);
    }
  }

  public getProductName(): string {
    return this.env.IYZICO_PRODUCT_NAME;
  }

  public getLaunchUrl(referenceId: string): string {
    return `${this.env.IYZICO_PUBLIC_BASE_URL}/v1/billing/checkouts/${encodeURIComponent(referenceId)}/launch`;
  }

  public getCallbackUrl(referenceId: string): string {
    const url = new URL(`${this.env.IYZICO_PUBLIC_BASE_URL}/v1/billing/callbacks/iyzico`);
    url.searchParams.set("reference_id", referenceId);
    url.searchParams.set("mode", "subscription");
    return url.toString();
  }

  public getProviderPlanName(plan: IyzicoCatalogPlanInput): string {
    return `elyan-${plan.planCode}-${plan.currencyCode.toLowerCase()}-${plan.monthlyPrice}-monthly-v1`;
  }

  public async listProducts(): Promise<Array<Record<string, unknown>>> {
    const response = await this.request("GET", "/v2/subscription/products?page=1&count=100");
    return this.readPagedList(response);
  }

  public async createProduct(input: { name: string; description?: string }): Promise<Record<string, unknown>> {
    const response = await this.request("POST", "/v2/subscription/products", {
      locale: this.env.IYZICO_LOCALE,
      conversationId: randomUUID(),
      name: input.name,
      description: input.description,
    });
    return this.readDataObject(response);
  }

  public async listPricingPlans(productReferenceCode: string): Promise<Array<Record<string, unknown>>> {
    const response = await this.request(
      "GET",
      `/v2/subscription/products/${encodeURIComponent(productReferenceCode)}/pricing-plans?page=1&count=100`,
    );
    return this.readPagedList(response);
  }

  public async createPricingPlan(
    productReferenceCode: string,
    input: IyzicoCatalogPlanInput,
  ): Promise<Record<string, unknown>> {
    const response = await this.request(
      "POST",
      `/v2/subscription/products/${encodeURIComponent(productReferenceCode)}/pricing-plans`,
      {
        locale: this.env.IYZICO_LOCALE,
        conversationId: randomUUID(),
        name: this.getProviderPlanName(input),
        price: input.monthlyPrice,
        currencyCode: input.currencyCode,
        paymentInterval: "MONTHLY",
        paymentIntervalCount: 1,
        planPaymentType: "RECURRING",
      },
    );

    return this.readDataObject(response);
  }

  public async initializeSubscriptionCheckout(input: IyzicoCheckoutInitInput): Promise<Record<string, unknown>> {
    return this.request("POST", "/v2/subscription/checkoutform/initialize", {
      locale: this.env.IYZICO_LOCALE,
      conversationId: input.conversationId,
      callbackUrl: input.callbackUrl,
      pricingPlanReferenceCode: input.pricingPlanReferenceCode,
      subscriptionInitialStatus: "ACTIVE",
      customer: input.customer,
    });
  }

  public async retrieveSubscriptionCheckout(token: string, conversationId?: string): Promise<Record<string, unknown>> {
    const suffix = conversationId ? `?conversationId=${encodeURIComponent(conversationId)}` : "";
    return this.request("GET", `/v2/subscription/checkoutform/${encodeURIComponent(token)}${suffix}`);
  }

  public async getSubscriptionDetail(subscriptionReferenceCode: string): Promise<Record<string, unknown>> {
    const response = await this.request(
      "GET",
      `/v2/subscription/subscriptions/${encodeURIComponent(subscriptionReferenceCode)}`,
    );
    return this.readDataObject(response);
  }

  public async cancelSubscription(subscriptionReferenceCode: string): Promise<void> {
    await this.request(
      "POST",
      `/v2/subscription/subscriptions/${encodeURIComponent(subscriptionReferenceCode)}/cancel`,
      {
        subscriptionReferenceCode,
      },
    );
  }

  public async upgradeSubscription(input: {
    subscriptionReferenceCode: string;
    newPricingPlanReferenceCode: string;
    upgradePeriod: "NOW" | "NEXT_PERIOD";
  }): Promise<Record<string, unknown>> {
    const response = await this.request(
      "POST",
      `/v2/subscription/subscriptions/${encodeURIComponent(input.subscriptionReferenceCode)}/upgrade`,
      {
        newPricingPlanReferenceCode: input.newPricingPlanReferenceCode,
        upgradePeriod: input.upgradePeriod,
        useTrial: false,
        resetRecurrenceCount: true,
      },
    );

    return this.readDataObject(response);
  }

  public validateWebhookSignatureV3(payload: Record<string, unknown>, headerValue: string): void {
    const signature = String(headerValue || "").trim();

    if (!signature) {
      throw unauthorized("iyzico_webhook_signature_missing");
    }

    const expected = this.computeWebhookSignatureV3(payload);

    if (!compareSignatures(signature, expected)) {
      throw unauthorized("iyzico_webhook_signature_invalid");
    }
  }

  public computeWebhookSignatureV3(payload: Record<string, unknown>): string {
    const secret = this.env.IYZICO_SECRET_KEY?.trim();

    if (!secret) {
      throw conflict("iyzico_config_missing:IYZICO_SECRET_KEY");
    }

    const eventType = String(payload.iyziEventType || payload.eventType || "").trim();
    const hasSubscriptionPayload =
      typeof payload.subscriptionReferenceCode === "string" ||
      eventType.toLowerCase().startsWith("subscription.");

    let message: string;

    if (hasSubscriptionPayload) {
      message =
        secret +
        String(payload.merchantId || this.env.IYZICO_MERCHANT_ID || "").trim() +
        eventType +
        String(payload.subscriptionReferenceCode || "").trim() +
        String(payload.orderReferenceCode || "").trim() +
        String(payload.customerReferenceCode || "").trim();
    } else if (Object.prototype.hasOwnProperty.call(payload, "token")) {
      message =
        secret +
        eventType +
        String(payload.iyziPaymentId || payload.paymentId || "").trim() +
        String(payload.token || "").trim() +
        String(payload.paymentConversationId || "").trim() +
        String(payload.status || "").trim();
    } else {
      message =
        secret +
        eventType +
        String(payload.paymentId || payload.iyziPaymentId || "").trim() +
        String(payload.paymentConversationId || "").trim() +
        String(payload.status || "").trim();
    }

    return createHmac("sha256", secret).update(message).digest("hex");
  }

  public normalizeSubscriptionStatus(status: string): "free" | "trialing" | "active" | "past_due" | "canceled" {
    const normalized = normalizeStatus(status);

    if (normalized === "active" || normalized === "success" || normalized === "paid" || normalized === "completed") {
      return "active";
    }

    if (normalized === "trial" || normalized === "trialing" || normalized === "pending") {
      return "trialing";
    }

    if (normalized === "failure" || normalized === "failed" || normalized === "unpaid" || normalized === "past_due") {
      return "past_due";
    }

    if (normalized === "canceled" || normalized === "cancelled" || normalized === "expired") {
      return "canceled";
    }

    return "free";
  }

  private getBaseUrl(): string {
    return this.env.IYZICO_BASE_URL.replace(/\/+$/, "");
  }

  private buildAuthHeaders(path: string, body?: IyzicoRequestBody): Record<string, string> {
    const secretKey = this.env.IYZICO_SECRET_KEY ?? "";
    const randomKey = `${Date.now()}${randomBytes(6).toString("hex")}`;
    const bodyText = body ? compactJson(body) : "";
    const signaturePayload = `${randomKey}${path}${bodyText}`;
    const signature = createHmac("sha256", secretKey).update(signaturePayload).digest("hex");
    const authorization = Buffer.from(
      `apiKey:${this.env.IYZICO_API_KEY ?? ""}&randomKey:${randomKey}&signature:${signature}`,
      "utf-8",
    ).toString("base64");

    return {
      Authorization: `IYZWSv2 ${authorization}`,
      "Content-Type": "application/json",
      Accept: "application/json",
      "x-iyzi-rnd": randomKey,
      "x-iyzi-client-version": "elyan-backend-billing/1.0",
    };
  }

  private async request(method: "GET" | "POST", path: string, body?: IyzicoRequestBody): Promise<Record<string, unknown>> {
    this.assertConfigured();

    let response: Response;

    try {
      response = await fetch(`${this.getBaseUrl()}${path}`, {
        method,
        headers: this.buildAuthHeaders(path, method === "GET" ? undefined : body),
        body: method === "GET" || !body ? undefined : compactJson(body),
        signal: AbortSignal.timeout(25_000),
      });
    } catch (error) {
      throw serviceUnavailable(error instanceof Error ? `iyzico_network_error:${error.message}` : "iyzico_network_error");
    }

    let payload: unknown;

    try {
      payload = await response.json();
    } catch {
      throw serviceUnavailable(`iyzico_invalid_response:${response.status}`);
    }

    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      throw serviceUnavailable(`iyzico_invalid_payload:${response.status}`);
    }

    const status = normalizeStatus((payload as Record<string, unknown>).status);

    if (!response.ok || status === "failure") {
      const errorCode = String((payload as Record<string, unknown>).errorCode || response.status).trim();
      const errorMessage = String(
        (payload as Record<string, unknown>).errorMessage ||
          (payload as Record<string, unknown>).error_message ||
          response.statusText ||
          "iyzico_request_failed",
      ).trim();
      throw badRequest(`iyzico_request_failed:${errorCode}:${errorMessage}`);
    }

    return payload as Record<string, unknown>;
  }

  private readDataObject(response: Record<string, unknown>): Record<string, unknown> {
    const data = response.data;

    if (!data || typeof data !== "object" || Array.isArray(data)) {
      throw conflict("iyzico_data_missing");
    }

    return data as Record<string, unknown>;
  }

  private readPagedList(response: Record<string, unknown>): Array<Record<string, unknown>> {
    const data = response.data;

    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return [];
    }

    const items =
      Array.isArray((data as Record<string, unknown>).items)
        ? ((data as Record<string, unknown>).items as Array<Record<string, unknown>>)
        : Array.isArray((data as Record<string, unknown>).data)
          ? ((data as Record<string, unknown>).data as Array<Record<string, unknown>>)
          : [];

    return items.filter((item) => item && typeof item === "object" && !Array.isArray(item));
  }
}
