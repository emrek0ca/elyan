import { and, desc, eq } from "drizzle-orm";
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { userConsents } from "../../db/schema.js";
import { AppError } from "../../lib/errors.js";

export const CONSENT_VERSIONS = {
  terms_of_service: "2026-07-04",
  privacy_policy: "2026-07-04",
  ai_data_sharing: "2026-07-04",
  cloud_speech: "2026-07-28",
} as const;

export const consentTypeSchema = z.enum([
  "terms_of_service",
  "privacy_policy",
  "ai_data_sharing",
  "cloud_speech",
]);

export type ConsentType = z.infer<typeof consentTypeSchema>;

export const grantConsentBodySchema = z.object({
  consentType: consentTypeSchema,
  consentVersion: z.string().trim().min(1).max(40),
  granted: z.boolean(),
});

export const revokeConsentBodySchema = z.object({
  consentType: consentTypeSchema,
});

export function createAiDataSharingConsentRequiredError(): AppError {
  return new AppError(
    403,
    "AI_DATA_SHARING_CONSENT_REQUIRED",
    "This feature needs permission to process your message or uploaded content with Elyan AI cloud processing before continuing.",
    {
      consentType: "ai_data_sharing",
      consentVersion: CONSENT_VERSIONS.ai_data_sharing,
      recipient: "Elyan AI cloud processing layer",
    },
  );
}

export function createCloudSpeechConsentRequiredError(): AppError {
  return new AppError(
    403,
    "CLOUD_SPEECH_CONSENT_REQUIRED",
    "Ses kaydını bulutta yazıya çevirmek için açık izin gerekiyor.",
    {
      consentType: "cloud_speech",
      consentVersion: CONSENT_VERSIONS.cloud_speech,
      recipient: "Elyan cloud speech processing",
    },
  );
}

async function readLatestConsent(
  app: FastifyInstance,
  userId: string,
  consentType: ConsentType,
) {
  const rows = await app.db
    .select()
    .from(userConsents)
    .where(
      and(
        eq(userConsents.userId, userId),
        eq(userConsents.consentType, consentType),
        eq(userConsents.consentVersion, CONSENT_VERSIONS[consentType]),
      ),
    )
    .orderBy(desc(userConsents.updatedAt))
    .limit(1);
  return rows[0] ?? null;
}

function shapeConsentStatus(
  type: ConsentType,
  row: Awaited<ReturnType<typeof readLatestConsent>>,
) {
  const granted = Boolean(row?.granted === true && !row.revokedAt);
  return {
    required: type === "terms_of_service" || type === "privacy_policy",
    requiredForCloudAI: type === "ai_data_sharing",
    requiredForCloudSpeech: type === "cloud_speech",
    granted,
    version: CONSENT_VERSIONS[type],
    grantedAt: row?.grantedAt?.toISOString?.() ?? null,
    revokedAt: row?.revokedAt?.toISOString?.() ?? null,
  };
}

export async function getConsentStatus(app: FastifyInstance, userId: string) {
  const [terms, privacy, ai, cloudSpeech] = await Promise.all([
    readLatestConsent(app, userId, "terms_of_service"),
    readLatestConsent(app, userId, "privacy_policy"),
    readLatestConsent(app, userId, "ai_data_sharing"),
    readLatestConsent(app, userId, "cloud_speech"),
  ]);
  return {
    termsOfService: shapeConsentStatus("terms_of_service", terms),
    privacyPolicy: shapeConsentStatus("privacy_policy", privacy),
    aiDataSharing: shapeConsentStatus("ai_data_sharing", ai),
    cloudSpeech: shapeConsentStatus("cloud_speech", cloudSpeech),
  };
}

export async function setUserConsent(
  app: FastifyInstance,
  input: {
    userId: string;
    consentType: ConsentType;
    consentVersion: string;
    granted: boolean;
    source: string;
    metadata?: Record<string, unknown>;
    returnStatus?: boolean;
  },
) {
  const now = new Date();
  const version = CONSENT_VERSIONS[input.consentType];
  if (input.consentVersion !== version) {
    throw new AppError(
      400,
      "consent_version_mismatch",
      "Consent version is not current.",
      {
        consentType: input.consentType,
        expectedVersion: version,
      },
    );
  }
  const values = {
    userId: input.userId,
    consentType: input.consentType,
    consentVersion: input.consentVersion,
    granted: input.granted,
    grantedAt: input.granted ? now : null,
    revokedAt: input.granted ? null : now,
    source: input.source,
    metadata: input.metadata ?? {},
    updatedAt: now,
  };
  await app.db
    .insert(userConsents)
    .values(values)
    .onConflictDoUpdate({
      target: [
        userConsents.userId,
        userConsents.consentType,
        userConsents.consentVersion,
      ],
      set: values,
    });
  if (input.returnStatus === false) {
    return undefined;
  }
  return getConsentStatus(app, input.userId);
}

export async function seedRegistrationConsents(
  app: FastifyInstance,
  input: {
    userId: string;
    termsAccepted: boolean;
    privacyAccepted: boolean;
    aiDataSharingAccepted?: boolean;
    source: string;
  },
) {
  await Promise.all([
    setUserConsent(app, {
      userId: input.userId,
      consentType: "terms_of_service",
      consentVersion: CONSENT_VERSIONS.terms_of_service,
      granted: input.termsAccepted,
      source: input.source,
      returnStatus: false,
    }),
    setUserConsent(app, {
      userId: input.userId,
      consentType: "privacy_policy",
      consentVersion: CONSENT_VERSIONS.privacy_policy,
      granted: input.privacyAccepted,
      source: input.source,
      returnStatus: false,
    }),
    input.aiDataSharingAccepted === undefined
      ? Promise.resolve()
      : setUserConsent(app, {
          userId: input.userId,
          consentType: "ai_data_sharing",
          consentVersion: CONSENT_VERSIONS.ai_data_sharing,
          granted: input.aiDataSharingAccepted,
          source: input.source,
          returnStatus: false,
        }),
  ]);
}

export async function assertAiDataSharingConsent(
  app: FastifyInstance,
  userId: string,
): Promise<boolean> {
  // The mobile consent flow is not a prerequisite until explicitly enabled.
  // Keeping the gate flag-controlled preserves the security control without
  // making a missing rollout flag block every normal chat request.
  if (app.config.ELYAN_AI_DATA_SHARING_CONSENT_REQUIRED !== true) {
    return false;
  }
  const status = await getConsentStatus(app, userId);
  if (!status.aiDataSharing.granted) {
    throw createAiDataSharingConsentRequiredError();
  }
  return true;
}

export async function assertCloudSpeechConsent(
  app: FastifyInstance,
  userId: string,
): Promise<true> {
  const row = await readLatestConsent(app, userId, "cloud_speech");
  if (!shapeConsentStatus("cloud_speech", row).granted) {
    throw createCloudSpeechConsentRequiredError();
  }
  return true;
}
