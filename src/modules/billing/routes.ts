import type { FastifyPluginAsync, FastifyReply, FastifyRequest } from "fastify";
import { getRequestContext } from "../../lib/http.js";
import { getIdempotencyKey } from "../../lib/idempotency.js";
import { getUserAuth } from "../../lib/request-auth.js";
import {
  billingCheckoutParamsSchema,
  billingProfileBodySchema,
  billingStorePurchaseBodySchema,
  callbackQuerySchema,
  changePlanBodySchema,
  createSubscriptionCheckoutBodySchema,
} from "./schemas.js";
import {
  cancelCurrentSubscription,
  completeSubscriptionCheckout,
  createSubscriptionCheckout,
  handleAppleStoreWebhook,
  handleGooglePlayWebhook,
  getBillingCheckout,
  getBillingProfileState,
  getBillingSummary,
  getCheckoutLaunchPayload,
  handleIyzicoWebhook,
  listBillingPlans,
  saveBillingProfile,
  updateSubscriptionPlan,
  verifyStorePurchase,
} from "./service.js";

export const billingRoutes: FastifyPluginAsync = async (app) => {
  app.get("/plans", async (request) => {
    return listBillingPlans(app, request.auth && request.auth.kind === "user" ? request.auth.sub : undefined);
  });

  app.get("/summary", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      billing: await getBillingSummary(app, auth.sub),
    };
  });

  app.get("/profile", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      profile: await getBillingProfileState(app, auth.sub),
    };
  });

  app.put("/profile", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = billingProfileBodySchema.parse(request.body);
    return {
      profile: await saveBillingProfile(app, auth.sub, body),
    };
  });

  app.post("/checkout/init", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = createSubscriptionCheckoutBodySchema.parse(request.body);
    const context = getRequestContext(request);
    const idempotencyKey = getIdempotencyKey(request);
    return {
      checkout: await createSubscriptionCheckout(app, auth.sub, {
        ...body,
        requestId: context.requestId,
        idempotencyKey,
      }),
    };
  });

  app.get("/checkouts/:referenceId", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const params = billingCheckoutParamsSchema.parse(request.params);
    return {
      checkout: await getBillingCheckout(app, params.referenceId, auth.sub),
    };
  });

  app.get("/checkouts/:referenceId/launch", async (request, reply) => {
    const params = billingCheckoutParamsSchema.parse(request.params);
    const payload = await getCheckoutLaunchPayload(app, params.referenceId);

    if (payload.checkoutFormContent) {
      reply.type("text/html").send(payload.checkoutFormContent);
      return;
    }

    if (payload.paymentPageUrl) {
      reply.redirect(payload.paymentPageUrl);
      return;
    }

    reply.status(404).send({
      error: "checkout_unavailable",
      message: "Checkout launch unavailable",
    });
  });

  const callbackHandler = async (request: FastifyRequest, reply: FastifyReply) => {
    const query = callbackQuerySchema.parse(request.query);
    const body =
      request.body && typeof request.body === "object" && !Array.isArray(request.body)
        ? (request.body as Record<string, unknown>)
        : {};
    const token = String(query.token || body.token || "").trim();
    const referenceId = String(query.reference_id || body.reference_id || "").trim() || undefined;
    const result = await completeSubscriptionCheckout(app, {
      token,
      referenceId,
    });

    const wantsJson =
      query.format === "json" || String(request.headers.accept || "").toLowerCase().includes("application/json");

    if (wantsJson) {
      return {
        checkout: result.checkout,
        billing: result.billing,
      };
    }

    reply.type("text/html").send(
      `<!doctype html><html><head><meta charset="utf-8"><title>Elyan Billing</title><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:40px;background:#f6f4ef;color:#111;"><h1 style="margin:0 0 12px;font-size:24px;">Payment ${result.checkout.status}</h1><p style="max-width:560px;line-height:1.6;">Billing state is updated. You can return to Elyan now.</p></body></html>`,
    );
  };

  app.get("/callbacks/iyzico", callbackHandler);
  app.post("/callbacks/iyzico", callbackHandler);

  app.post("/webhooks/iyzico", async (request) => {
    const payload =
      request.body && typeof request.body === "object" && !Array.isArray(request.body)
        ? (request.body as Record<string, unknown>)
        : {};
    return {
      event: await handleIyzicoWebhook(app, payload, request.headers),
    };
  });

  app.post("/webhooks/apple", async (request) => {
    const payload =
      request.body && typeof request.body === "object" && !Array.isArray(request.body)
        ? (request.body as Record<string, unknown>)
        : {};
    return {
      event: await handleAppleStoreWebhook(app, payload),
    };
  });

  app.post("/webhooks/google", async (request) => {
    const payload =
      request.body && typeof request.body === "object" && !Array.isArray(request.body)
        ? (request.body as Record<string, unknown>)
        : {};
    return {
      event: await handleGooglePlayWebhook(app, payload),
    };
  });

  app.post("/subscription/change-plan", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = changePlanBodySchema.parse(request.body);
    return {
      billing: await updateSubscriptionPlan(app, auth.sub, body),
    };
  });

  app.post("/subscription/cancel", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    return {
      billing: await cancelCurrentSubscription(app, auth.sub),
    };
  });

  app.post("/store/verify", async (request, reply) => {
    await app.authenticateUser(request, reply);

    if (reply.sent) {
      return;
    }

    const auth = getUserAuth(request);
    const body = billingStorePurchaseBodySchema.parse(request.body);
    return {
      billing: await verifyStorePurchase(app, auth.sub, body),
    };
  });
};
