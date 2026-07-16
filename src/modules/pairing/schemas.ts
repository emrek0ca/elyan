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

const mobileDeviceSchema = z
  .object({
    label: z.string().min(1).max(120),
    platform: z.string().min(1).max(120),
    appVersion: z.string().min(1).max(80).optional(),
  })
  .optional();

export const claimPairSessionBodySchema = z.object({
  pairingCode: z.string().min(6).max(24),
  mobileDevice: mobileDeviceSchema,
});

// Kısa kodla claim (QR'sız): sessionId gerekmez; kod globally unique olduğu
// için backend session'ı koddan çözer.
export const claimPairSessionByCodeBodySchema = z.object({
  pairingCode: z.string().min(6).max(24),
  mobileDevice: mobileDeviceSchema,
});
