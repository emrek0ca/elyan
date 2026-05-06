import { env } from '@/lib/env';

export type RuntimeVersionInfo = {
  version: string;
  releaseTag: string;
  buildSha?: string;
};

const PACKAGE_VERSION = process.env.npm_package_version ?? '1.3.0';

export function getRuntimeVersionInfo(): RuntimeVersionInfo {
  return {
    version: PACKAGE_VERSION,
    releaseTag: env.ELYAN_RELEASE_TAG?.trim() || PACKAGE_VERSION,
    buildSha: env.ELYAN_BUILD_SHA?.trim() || undefined,
  };
}
