import { z } from "zod";

export const createPairSessionBodySchema = z.object({
  deviceLabel: z.string().min(1).max(120),
  platform: z.string().min(1).max(120),
  runtimeVersion: z.string().min(1).max(80).optional(),
  externalDeviceId: z.string().min(1).max(160).optional(),
});

export const pairSessionParamsSchema = z.object({
  sessionId: z.string().uuid(),
});

export const claimPairSessionBodySchema = z.object({
  pairingCode: z.string().min(6).max(24),
  mobileDevice: z
    .object({
      label: z.string().min(1).max(120),
      platform: z.string().min(1).max(120),
      appVersion: z.string().min(1).max(80).optional(),
    })
    .optional(),
});
