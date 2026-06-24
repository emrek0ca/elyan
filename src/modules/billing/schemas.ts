import { z } from "zod";

export const billingProfileBodySchema = z.object({
  fullName: z.string().trim().min(3).max(160),
  email: z.string().trim().email().max(320),
  phone: z.string().trim().min(6).max(32),
  identityNumber: z
    .string()
    .trim()
    .min(5)
    .max(32)
    .regex(/^[0-9A-Za-z]+$/),
  addressLine1: z.string().trim().min(5).max(255),
  city: z.string().trim().min(2).max(120),
  country: z.string().trim().min(2).max(120),
  zipCode: z.string().trim().min(2).max(32),
});

export const createSubscriptionCheckoutBodySchema = z.object({
  planCode: z.enum(["solo", "pro"]),
  successUrl: z.string().url().optional(),
  cancelUrl: z.string().url().optional(),
});

export const billingCheckoutParamsSchema = z.object({
  referenceId: z.string().uuid(),
});

export const callbackQuerySchema = z.object({
  token: z.string().min(1).optional(),
  reference_id: z.string().uuid().optional(),
  mode: z.string().optional(),
  format: z.enum(["json"]).optional(),
});

export const changePlanBodySchema = z.object({
  planCode: z.enum(["solo", "pro"]),
  effectiveAt: z.enum(["now", "next_period"]).default("next_period"),
});

export const billingStorePurchaseBodySchema = z.object({
  platform: z.enum(["apple", "google"]),
  planCode: z.enum(["solo", "pro"]),
  productId: z.string().trim().min(1).max(160),
  verificationData: z.string().trim().min(1).max(200_000),
  transactionId: z.string().trim().min(1).max(160).optional(),
  originalTransactionId: z.string().trim().min(1).max(160).optional(),
  packageName: z.string().trim().min(1).max(160).optional(),
});
