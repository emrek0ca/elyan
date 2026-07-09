import { z } from "zod";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";

export const registerMobileDeviceBodySchema = z.object({
  externalDeviceId: z.string().min(1).max(160),
  label: z.string().min(1).max(120),
  platform: z.string().min(1).max(120),
  appVersion: z.string().min(1).max(80).optional(),
  pushToken: z.string().min(1).max(4096).optional().nullable(),
  pushProvider: z.string().min(1).max(40).optional().nullable(),
  notificationAuthorizationStatus: z.string().min(1).max(40).optional().nullable(),
  supportsLiveActivities: z.boolean().optional(),
  supportsDynamicIsland: z.boolean().optional(),
  backgroundRefreshEnabled: z.boolean().optional(),
  buildMetadata: boundedJsonRecordSchema.optional(),
});

export const deviceParamsSchema = z.object({
  deviceId: z.string().uuid(),
});
