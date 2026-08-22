import { z } from "zod";
import { boundedJsonRecordSchema } from "../../lib/json-boundary.js";

/** Server-owned vocabulary for the mobile surfaces that can be declared. */
export const mobileCapabilityValues = [
  "camera",
  "location",
  "notifications",
  "share",
  "photo_library",
  "microphone",
  "present_file",
] as const;

const mobileCapabilitySchema = z.enum(mobileCapabilityValues);

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
  capabilities: z.array(mobileCapabilitySchema).max(64).optional(),
  buildMetadata: boundedJsonRecordSchema.optional(),
});

/**
 * FCM rotates registration tokens independently of app launches, so the client
 * needs a cheap way to push just the token without replaying the whole
 * registration payload.
 */
export const updatePushTokenBodySchema = z.object({
  externalDeviceId: z.string().min(1).max(160),
  pushToken: z.string().min(1).max(4096).nullable(),
  pushProvider: z.string().min(1).max(40).optional(),
  notificationAuthorizationStatus: z.string().min(1).max(40).optional(),
});

export const deviceParamsSchema = z.object({
  deviceId: z.string().uuid(),
});
