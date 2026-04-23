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

  return process.env.GITHUB_REPOSITORY ?? 'elyan-dev/elyan';
}

function hasRequiredAssets(assets: Array<{ name: string }>) {
  const assetNames = new Set(assets.map((asset) => asset.name));
  return requiredAssets.every((name) => assetNames.has(name));
}

function normalizeVersionTag(tagName: string) {
  return tagName.trim().replace(/^v/i, '');
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
  const publishable = json.find(
    (release) => !release.draft && !release.prerelease && release.published_at && hasRequiredAssets(release.assets)
  );

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
  const updateAvailable = Boolean(release && latestVersion && latestVersion !== currentVersion);

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
        : `Current runtime ${currentTagName} matches the latest publishable release.`
      : 'No publishable release is currently available.',
  };
}
