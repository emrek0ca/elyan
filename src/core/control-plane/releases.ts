import { z } from 'zod';
import packageJson from '../../../package.json';
import {
  controlPlaneReleaseAssetSchema,
  controlPlaneReleaseSnapshotSchema,
  type ControlPlaneReleaseSnapshot,
} from './types';

const requiredAssets = [
  'elyan-macos-arm64.zip',
  'elyan-macos-x64.zip',
  'elyan-linux-x64.tar.gz',
  'elyan-windows-x64.zip',
] as const;

const githubReleaseSchema = z.object({
  tag_name: z.string(),
  name: z.string().nullable().optional(),
  html_url: z.string().url(),
  url: z.string().url(),
  draft: z.boolean(),
  prerelease: z.boolean(),
  published_at: z.string().nullable(),
  assets: z.array(
    z.object({
      name: z.string(),
      size: z.number().nonnegative(),
      browser_download_url: z.string().url(),
    })
  ),
});

function getRepositorySlug() {
  const owner = process.env.GITHUB_OWNER?.trim();
  const repo = process.env.GITHUB_REPO?.trim();

  if (owner && repo) {
    return `${owner}/${repo}`;
  }

  return process.env.GITHUB_REPOSITORY ?? 'emrek0ca/elyan';
}

function hasRequiredAssets(assets: Array<{ name: string }>) {
  const assetNames = new Set(assets.map((asset) => asset.name));
  return requiredAssets.every((name) => assetNames.has(name));
}

function normalizeVersionTag(tagName: string) {
  return tagName.trim().replace(/^v/i, '');
}

function parseVersionParts(value: string) {
  const [major = '0', minor = '0', patch = '0'] = normalizeVersionTag(value).split('.');

  return {
    major: Number.parseInt(major, 10) || 0,
    minor: Number.parseInt(minor, 10) || 0,
    patch: Number.parseInt(patch, 10) || 0,
  };
}

function compareVersionTags(left: string, right: string) {
  const leftParts = parseVersionParts(left);
  const rightParts = parseVersionParts(right);

  if (leftParts.major !== rightParts.major) {
    return leftParts.major - rightParts.major;
  }

  if (leftParts.minor !== rightParts.minor) {
    return leftParts.minor - rightParts.minor;
  }

  return leftParts.patch - rightParts.patch;
}

function comparePublishedAt(left: string | null | undefined, right: string | null | undefined) {
  const leftTime = left ? Date.parse(left) : 0;
  const rightTime = right ? Date.parse(right) : 0;
  return leftTime - rightTime;
}

function selectLatestPublishableRelease(
  releases: Array<z.infer<typeof githubReleaseSchema>>
): z.infer<typeof githubReleaseSchema> | null {
  const publishable = releases.filter(
    (release) => !release.draft && !release.prerelease && release.published_at && hasRequiredAssets(release.assets)
  );

  return publishable.reduce<z.infer<typeof githubReleaseSchema> | null>((latest, candidate) => {
    if (!latest) {
      return candidate;
    }

    const versionCompare = compareVersionTags(candidate.tag_name, latest.tag_name);
    if (versionCompare > 0) {
      return candidate;
    }

    if (versionCompare < 0) {
      return latest;
    }

    return comparePublishedAt(candidate.published_at, latest.published_at) > 0 ? candidate : latest;
  }, null);
}

export async function getLatestElyanReleaseSnapshot(): Promise<ControlPlaneReleaseSnapshot | null> {
  const repository = getRepositorySlug();
  const headers: Record<string, string> = {
    Accept: 'application/vnd.github+json',
    'User-Agent': 'Elyan-Control-Plane',
  };

  if (process.env.GITHUB_TOKEN) {
    headers.Authorization = `Bearer ${process.env.GITHUB_TOKEN}`;
  }

  const response = await fetch(`https://api.github.com/repos/${repository}/releases?per_page=10`, {
    headers,
  });

  if (!response.ok) {
    throw new Error(`GitHub releases request failed with status ${response.status}`);
  }

  const json = githubReleaseSchema.array().parse(await response.json());
  const publishable = selectLatestPublishableRelease(json);

  if (!publishable) {
    return null;
  }

  const assets = publishable.assets
    .filter((asset) => requiredAssets.includes(asset.name as (typeof requiredAssets)[number]))
    .map((asset) => controlPlaneReleaseAssetSchema.parse({
      name: asset.name,
      size: asset.size,
      browserDownloadUrl: asset.browser_download_url,
    }));

  return controlPlaneReleaseSnapshotSchema.parse({
    repository,
    tagName: publishable.tag_name,
    name: publishable.name ?? publishable.tag_name,
    publishedAt: publishable.published_at,
    url: publishable.url,
    htmlUrl: publishable.html_url,
    assets,
    requiredAssets: [...requiredAssets],
    complete: true,
  });
}

export async function getLatestElyanReleaseResponse() {
  const release = await getLatestElyanReleaseSnapshot().catch(() => null);
  const currentVersion = packageJson.version;
  const currentTagName = `v${currentVersion}`;
  const latestVersion = release ? normalizeVersionTag(release.tagName) : null;
  const versionCompare = release ? compareVersionTags(latestVersion ?? '', currentVersion) : 0;
  const updateAvailable = Boolean(release && versionCompare > 0);
  const runtimeIsNewer = Boolean(release && versionCompare < 0);

  return {
    ok: true,
    repository: getRepositorySlug(),
    currentVersion,
    currentTagName,
    requiredAssets: [...requiredAssets],
    latest: release,
    publishable: Boolean(release),
    updateAvailable,
    updateStatus: release ? (updateAvailable ? 'update_available' : 'current') : 'unavailable',
    updateMessage: release
      ? updateAvailable
        ? `Latest publishable release ${release.tagName} is newer than ${currentTagName}.`
        : runtimeIsNewer
          ? `Current runtime ${currentTagName} is newer than the latest publishable release ${release.tagName}.`
          : `Current runtime ${currentTagName} matches the latest publishable release.`
      : 'No publishable release is currently available.',
  };
}
