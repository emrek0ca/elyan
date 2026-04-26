import { describe, expect, it } from 'vitest';
import {
  downloadPlatformCards,
  formatReleaseVersion,
  getMissingReleaseAssets,
  isReleaseMatrixComplete,
  resolvePlatformAssets,
} from '@/core/control-plane/downloads';

const requiredAssets = [
  'elyan-macos-arm64.zip',
  'elyan-macos-x64.zip',
  'elyan-linux-x64.tar.gz',
  'elyan-windows-x64.zip',
];

const targets = [
  {
    platform: 'macos' as const,
    architecture: 'arm64' as const,
    format: 'zip' as const,
    name: 'elyan-macos-arm64.zip',
    browserDownloadUrl: 'https://example.com/elyan-macos-arm64.zip',
    size: 10,
    label: 'macOS arm64',
  },
  {
    platform: 'linux' as const,
    architecture: 'x64' as const,
    format: 'tar.gz' as const,
    name: 'elyan-linux-x64.tar.gz',
    browserDownloadUrl: 'https://example.com/elyan-linux-x64.tar.gz',
    size: 10,
    label: 'Linux x64',
  },
];

describe('download surface helpers', () => {
  it('keeps exact install cards for supported v1.2 platforms', () => {
    expect(downloadPlatformCards.map((card) => card.key)).toEqual(['macos', 'linux', 'windows']);
    expect(downloadPlatformCards.every((card) => card.setupCommand === 'elyan setup --zero-cost')).toBe(true);
  });

  it('filters release targets by platform without inventing unavailable assets', () => {
    expect(resolvePlatformAssets(targets, 'macos').map((target) => target.name)).toEqual(['elyan-macos-arm64.zip']);
    expect(resolvePlatformAssets(targets, 'windows')).toEqual([]);
  });

  it('reports incomplete release matrices honestly', () => {
    expect(isReleaseMatrixComplete(requiredAssets, targets)).toBe(false);
    expect(getMissingReleaseAssets(requiredAssets, targets)).toEqual(['elyan-macos-x64.zip', 'elyan-windows-x64.zip']);
  });

  it('formats release tags for display', () => {
    expect(formatReleaseVersion('v1.2.0')).toBe('1.2.0');
    expect(formatReleaseVersion(undefined)).toBe('unknown');
  });
});
