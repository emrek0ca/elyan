import { z } from 'zod';
import packageJson from '../../../package.json';
import { env } from '@/lib/env';
import { getControlPlanePool } from './database';
import {
  controlPlaneReleaseAssetSchema,
  controlPlaneReleaseSnapshotSchema,
  controlPlaneReleaseTargetSchema,
  type ControlPlaneReleaseSnapshot,
  type ControlPlaneReleaseTarget,
} from './types';

const requiredAssets = [
  'elyan-macos-arm64.zip',
  'elyan-macos-x64.zip',
  'elyan-linux-x64.tar.gz',
  'elyan-windows-x64.zip',
] as const;

const RELEASE_CACHE_TTL_MS = 24 * 60 * 60 * 1000;

type ReleaseTargetDefinition = {
  name: (typeof requiredAssets)[number];
  platform: ControlPlaneReleaseTarget['platform'];
  architecture: ControlPlaneReleaseTarget['architecture'];
  format: ControlPlaneReleaseTarget['format'];
  label: string;
};

const releaseTargetDefinitions: ReleaseTargetDefinition[] = [
  {
    name: 'elyan-macos-arm64.zip',
    platform: 'macos',
    architecture: 'arm64',
    format: 'zip',
    label: 'macOS arm64',
  },
  {
    name: 'elyan-macos-x64.zip',
    platform: 'macos',
    architecture: 'x64',
    format: 'zip',
    label: 'macOS x64',
  },
  {
    name: 'elyan-linux-x64.tar.gz',
    platform: 'linux',
    architecture: 'x64',
    format: 'tar.gz',
    label: 'Linux x64',
  },
  {
    name: 'elyan-windows-x64.zip',
    platform: 'windows',
    architecture: 'x64',
    format: 'zip',
    label: 'Windows x64',
  },
];

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

function buildReleaseTarget(asset: { name: string; size: number; browser_download_url: string }) {
  const definition = releaseTargetDefinitions.find((entry) => entry.name === asset.name);
  if (!definition) {
    return null;
  }

  return controlPlaneReleaseTargetSchema.parse({
    platform: definition.platform,
    architecture: definition.architecture,
    format: definition.format,
    name: asset.name,
    browserDownloadUrl: asset.browser_download_url,
    size: asset.size,
    label: definition.label,
  });
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

function isReleaseCacheFresh(refreshedAt?: string | null, expiresAt?: string | null) {
  if (expiresAt) {
    return Date.parse(expiresAt) > Date.now();
  }

  if (!refreshedAt) {
    return false;
  }

  return Date.now() - Date.parse(refreshedAt) < RELEASE_CACHE_TTL_MS;
}

async function readCachedReleaseSnapshot(repository: string): Promise<ControlPlaneReleaseSnapshot | null> {
  if (!env.DATABASE_URL) {
    return null;
  }

  try {
    const pool = getControlPlanePool(env.DATABASE_URL);
    const result = await pool.query<{
      payload: unknown;
      refreshed_at: string | null;
      expires_at: string | null;
    }>(
      `
        SELECT payload, refreshed_at, expires_at
        FROM release_cache
        WHERE repository = $1
        LIMIT 1
      `,
      [repository]
    );

    const row = result.rows[0];
    if (!row || !isReleaseCacheFresh(row.refreshed_at, row.expires_at)) {
      return null;
    }

    return controlPlaneReleaseSnapshotSchema.parse(row.payload);
  } catch {
    return null;
  }
}

async function writeCachedReleaseSnapshot(repository: string, snapshot: ControlPlaneReleaseSnapshot) {
  if (!env.DATABASE_URL) {
    return;
  }

  try {
    const pool = getControlPlanePool(env.DATABASE_URL);
    await pool.query(
      `
        INSERT INTO release_cache (
          repository,
          tag_name,
          payload,
          refreshed_at,
          expires_at
        )
        VALUES ($1, $2, $3::jsonb, NOW(), NOW() + INTERVAL '24 hours')
        ON CONFLICT (repository) DO UPDATE SET
          tag_name = EXCLUDED.tag_name,
          payload = EXCLUDED.payload,
          refreshed_at = EXCLUDED.refreshed_at,
          expires_at = EXCLUDED.expires_at
      `,
      [repository, snapshot.tagName, JSON.stringify(snapshot)]
    );
  } catch {
    return;
  }
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
  const cached = await readCachedReleaseSnapshot(repository);
  if (cached) {
    return cached;
  }

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
  const targets = publishable.assets
    .map((asset) => buildReleaseTarget(asset))
    .filter((asset): asset is ControlPlaneReleaseTarget => Boolean(asset));

  const snapshot = controlPlaneReleaseSnapshotSchema.parse({
    repository,
    tagName: publishable.tag_name,
    name: publishable.name ?? publishable.tag_name,
    publishedAt: publishable.published_at,
    url: publishable.url,
    htmlUrl: publishable.html_url,
    assets,
    targets,
    requiredAssets: [...requiredAssets],
    complete: true,
  });

  await writeCachedReleaseSnapshot(repository, snapshot);

  return snapshot;
}

export async function getLatestElyanReleaseResponse() {
  const release = await getLatestElyanReleaseSnapshot().catch(() => null);
  const currentVersion = packageJson.version;
  const currentTagName = `v${currentVersion}`;
  const latestVersion = release ? normalizeVersionTag(release.tagName) : null;
  const versionCompare = release ? compareVersionTags(latestVersion ?? '', currentVersion) : 0;
  const updateAvailable = Boolean(release && versionCompare > 0);
  const runtimeIsNewer = Boolean(release && versionCompare < 0);
  const targets = release?.targets ?? [];

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
    targets,
  };
}
