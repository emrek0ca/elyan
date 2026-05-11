import { z } from "zod";

export const registerMobileDeviceBodySchema = z.object({
  externalDeviceId: z.string().min(1).max(160),
  label: z.string().min(1).max(120),
  platform: z.string().min(1).max(120),
  appVersion: z.string().min(1).max(80).optional(),
});

export const deviceParamsSchema = z.object({
  deviceId: z.string().uuid(),
});
