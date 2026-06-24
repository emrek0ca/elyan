import type { FastifyPluginAsync } from "fastify";
import type { AppEnv } from "../../config/env.js";

const AASA_PATH = "/.well-known/apple-app-site-association";
const ASSET_LINKS_PATH = "/.well-known/assetlinks.json";

function readString(value: unknown): string {
  return String(value ?? "").trim();
}

function splitCommaSeparated(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function buildAppleAppSiteAssociationPayload(
  env: Pick<AppEnv, "APPLE_TEAM_ID" | "APPLE_APP_BUNDLE_ID">,
) {
  const teamId = readString(env.APPLE_TEAM_ID);
  const bundleId = readString(env.APPLE_APP_BUNDLE_ID);
  const appId = teamId && bundleId ? `${teamId}.${bundleId}` : "";

  return {
    applinks: {
      apps: [],
      details: appId
        ? [
            {
              appID: appId,
              paths: ["*"],
            },
          ]
        : [],
    },
  };
}

export function buildAndroidAssetLinksPayload(
  env: Pick<AppEnv, "ANDROID_APP_LINK_PACKAGE_NAME" | "ANDROID_SHA256_CERT_FINGERPRINTS">,
) {
  const packageName = readString(env.ANDROID_APP_LINK_PACKAGE_NAME) || "com.elyan.elyanMobile";
  const fingerprints = splitCommaSeparated(readString(env.ANDROID_SHA256_CERT_FINGERPRINTS));

  if (!packageName || fingerprints.length === 0) {
    return [] as Array<Record<string, unknown>>;
  }

  return [
    {
      relation: ["delegate_permission/common.handle_all_urls"],
      target: {
        namespace: "android_app",
        package_name: packageName,
        sha256_cert_fingerprints: fingerprints,
      },
    },
  ];
}

export function getMobileNativeLinksReadiness(
  env: Pick<
    AppEnv,
    "APPLE_TEAM_ID" | "APPLE_APP_BUNDLE_ID" | "ANDROID_APP_LINK_PACKAGE_NAME" | "ANDROID_SHA256_CERT_FINGERPRINTS"
  >,
) {
  const appleTeamId = readString(env.APPLE_TEAM_ID);
  const appleBundleId = readString(env.APPLE_APP_BUNDLE_ID);
  const androidPackageName = readString(env.ANDROID_APP_LINK_PACKAGE_NAME) || "com.elyan.elyanMobile";
  const androidFingerprints = splitCommaSeparated(readString(env.ANDROID_SHA256_CERT_FINGERPRINTS));

  const appleReady = Boolean(appleTeamId && appleBundleId);
  const androidReady = Boolean(androidPackageName && androidFingerprints.length > 0);

  return {
    ready: appleReady || androidReady,
    appleReady,
    androidReady,
    missingEnv: [
      !appleTeamId ? "APPLE_TEAM_ID" : null,
      !appleBundleId ? "APPLE_APP_BUNDLE_ID" : null,
      !androidPackageName ? "ANDROID_APP_LINK_PACKAGE_NAME" : null,
      androidFingerprints.length === 0 ? "ANDROID_SHA256_CERT_FINGERPRINTS" : null,
    ].filter((value): value is string => Boolean(value)),
    apple: {
      teamId: appleTeamId,
      bundleId: appleBundleId,
      associationUrlPaths: [AASA_PATH],
    },
    android: {
      packageName: androidPackageName,
      fingerprintCount: androidFingerprints.length,
      associationUrlPaths: [ASSET_LINKS_PATH],
    },
  };
}

export const mobileNativeLinksRoutes: FastifyPluginAsync = async (app) => {
  app.get(AASA_PATH, async (_request, reply) => {
    reply.header("cache-control", "public, max-age=300");
    reply.header("content-type", "application/json");
    return buildAppleAppSiteAssociationPayload(app.config);
  });

  app.get(ASSET_LINKS_PATH, async (_request, reply) => {
    reply.header("cache-control", "public, max-age=300");
    reply.header("content-type", "application/json");
    return buildAndroidAssetLinksPayload(app.config);
  });
};

