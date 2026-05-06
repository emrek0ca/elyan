import type { ControlPlaneReleaseTarget } from './types';

export type DownloadPlatform = 'macos' | 'linux' | 'windows';

export type DownloadPlatformCard = {
  key: DownloadPlatform;
  title: string;
  detail: string;
  installCommand: string;
  setupCommand: string;
};

export const downloadPlatformCards: DownloadPlatformCard[] = [
  {
    key: 'macos',
    title: 'macOS',
    detail: 'Apple Silicon and Intel builds for local desktop installs.',
    installCommand: 'curl -L -O https://github.com/emrek0ca/elyan/releases/latest/download/elyan-macos-arm64.zip',
    setupCommand: 'elyan setup',
  },
  {
    key: 'linux',
    title: 'Linux',
    detail: '64-bit Linux archive for servers, workstations, and VPS nodes.',
    installCommand: 'curl -L https://github.com/emrek0ca/elyan/releases/latest/download/elyan-linux-x64.tar.gz | tar -xz',
    setupCommand: 'elyan setup',
  },
  {
    key: 'windows',
    title: 'Windows',
    detail: '64-bit Windows archive for native local installs.',
    installCommand: 'iwr https://github.com/emrek0ca/elyan/releases/latest/download/elyan-windows-x64.zip -OutFile elyan-windows-x64.zip',
    setupCommand: 'elyan setup',
  },
];

export function resolvePlatformAssets(
  targets: Array<Pick<ControlPlaneReleaseTarget, 'platform' | 'label' | 'browserDownloadUrl' | 'name'>>,
  platform: DownloadPlatform
) {
  return targets.filter((target) => target.platform === platform);
}

export function formatReleaseVersion(tagName?: string) {
  return tagName?.startsWith('v') ? tagName.slice(1) : tagName ?? 'unknown';
}

export function isReleaseMatrixComplete(requiredAssets: string[], targets: Array<{ name: string }>) {
  const available = new Set(targets.map((target) => target.name));
  return requiredAssets.every((assetName) => available.has(assetName));
}

export function getMissingReleaseAssets(requiredAssets: string[], targets: Array<{ name: string }>) {
  const available = new Set(targets.map((target) => target.name));
  return requiredAssets.filter((assetName) => !available.has(assetName));
}
