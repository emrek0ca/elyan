import { z } from "zod";
import { connectionProviderSchema } from "../../contracts/domain.js";

const legalAcceptanceSchema = z.object({
  termsAccepted: z.boolean().optional(),
  privacyAccepted: z.boolean().optional(),
});

export const registerBodySchema = z.object({
  email: z.string().email().max(320),
  password: z.string().min(8).max(128),
  displayName: z.string().min(1).max(120).optional(),
  legalAcceptance: legalAcceptanceSchema.optional(),
  termsAccepted: z.boolean().optional(),
  privacyAccepted: z.boolean().optional(),
});

export const loginBodySchema = z.object({
  email: z.string().email().max(320),
  password: z.string().min(8).max(128),
  twoFactorCode: z.string().trim().regex(/^[0-9 ]{6,12}$/).optional(),
});

export const refreshBodySchema = z.object({
  refreshToken: z.string().min(1),
});

export const updateProfileBodySchema = z.object({
  displayName: z.string().min(1).max(120),
});

export const changePasswordBodySchema = z.object({
  currentPassword: z.string().min(8).max(128),
  nextPassword: z.string().min(8).max(128),
});

export const uploadAvatarBodySchema = z.object({
  mimeType: z.enum(["image/png", "image/jpeg", "image/webp"]),
  dataBase64: z.string().min(1).max(3_000_000),
});

export const verifyTwoFactorBodySchema = z.object({
  code: z.string().trim().regex(/^[0-9 ]{6,12}$/),
});

export const disableTwoFactorBodySchema = z.object({
  code: z.string().trim().regex(/^[0-9 ]{6,12}$/),
});

export const oauthProviderParamsSchema = z.object({
  provider: connectionProviderSchema.refine(
    (value) => value === "google" || value === "apple",
    { message: "Unsupported auth provider" },
  ),
});

export const oauthLoginBodySchema = z.object({
  idToken: z.string().min(1),
  authorizationCode: z.string().min(1).optional(),
  email: z.string().email().max(320).optional(),
  displayName: z.string().min(1).max(120).optional(),
  legalAcceptance: legalAcceptanceSchema.optional(),
  termsAccepted: z.boolean().optional(),
  privacyAccepted: z.boolean().optional(),
});
