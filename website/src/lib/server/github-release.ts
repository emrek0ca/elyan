export type ReleasePlatform = 'macos' | 'windows' | 'linux';

export type GitHubReleaseAsset = {
  name?: string;
  browser_download_url?: string;
  content_type?: string;
  size?: number;
};

export type GitHubRelease = {
  tag_name?: string;
  assets?: GitHubReleaseAsset[];
};

const LATEST_RELEASE_URL = 'https://api.github.com/repos/emrek0ca/elyan/releases/latest';

function includesAny(value: string, needles: string[]): boolean {
  return needles.some((needle) => value.includes(needle));
}

export function normalizePlatform(value: string | undefined): ReleasePlatform | null {
  const normalized = (value || '').toLowerCase();
  if (normalized === 'mac' || normalized === 'macos' || normalized === 'darwin') return 'macos';
  if (normalized === 'win' || normalized === 'windows') return 'windows';
  if (normalized === 'linux') return 'linux';
  return null;
}

export function scoreReleaseAsset(asset: GitHubReleaseAsset, platform: ReleasePlatform): number {
  const name = asset.name?.toLowerCase() ?? '';
  const url = asset.browser_download_url ?? '';
  if (!name || !url) return -1;
  if (includesAny(name, ['.sha256', 'sha256sums', 'sbom', '.cdx.json'])) return -1;

  if (platform === 'macos') {
    if (includesAny(name, ['windows', 'win32', 'win64', 'linux', 'appimage', '.deb', '.rpm'])) return -1;
    let score = 0;
    if (includesAny(name, ['macos', 'darwin', 'osx', 'mac'])) score += 20;
    if (name.endsWith('.dmg')) score += 20;
    if (name.endsWith('.pkg')) score += 14;
    if (name.endsWith('.app.zip') || name.endsWith('.zip')) score += 8;
    if (includesAny(name, ['arm64', 'aarch64'])) score += 2;
    if (includesAny(name, ['universal', 'x64', 'x86_64'])) score += 1;
    return score > 0 ? score : -1;
  }

  if (platform === 'windows') {
    if (includesAny(name, ['macos', 'darwin', 'osx', 'linux', 'appimage', '.deb', '.rpm'])) return -1;
    let score = 0;
    if (includesAny(name, ['windows', 'win32', 'win64', 'win'])) score += 20;
    if (includesAny(name, ['setup.exe', 'installer.exe'])) score += 22;
    else if (name.endsWith('.exe')) score += 16;
    if (name.endsWith('.msi')) score += 15;
    if (name.endsWith('.zip')) score += 8;
    if (includesAny(name, ['x64', 'x86_64'])) score += 2;
    if (includesAny(name, ['arm64'])) score += 1;
    return score > 0 ? score : -1;
  }

  if (includesAny(name, ['macos', 'darwin', 'osx', 'windows', 'win32', 'win64', '.exe', '.msi', '.dmg', '.pkg'])) return -1;
  let score = 0;
  if (includesAny(name, ['linux'])) score += 20;
  if (name.endsWith('.deb')) score += 20;
  if (name.endsWith('.appimage')) score += 16;
  if (name.endsWith('.rpm')) score += 12;
  if (name.endsWith('.tar.gz') || name.endsWith('.tgz')) score += 8;
  if (includesAny(name, ['x64', 'x86_64'])) score += 2;
  if (includesAny(name, ['arm64', 'aarch64'])) score += 1;
  return score > 0 ? score : -1;
}

export function pickReleaseAsset(assets: GitHubReleaseAsset[], platform: ReleasePlatform): GitHubReleaseAsset | null {
  return assets
    .map((asset) => ({ asset, score: scoreReleaseAsset(asset, platform) }))
    .filter((candidate) => candidate.score >= 0)
    .sort((a, b) => b.score - a.score)[0]?.asset ?? null;
}

export async function fetchLatestElyanRelease(): Promise<GitHubRelease> {
  const response = await fetch(LATEST_RELEASE_URL, {
    headers: {
      accept: 'application/vnd.github+json',
      'user-agent': 'elyan-website',
    },
  });
  if (!response.ok) throw new Error(`github_release_${response.status}`);
  return await response.json() as GitHubRelease;
}
