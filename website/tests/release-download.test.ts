import { describe, expect, it } from 'vitest';
import {
  normalizePlatform,
  pickReleaseAsset,
  scoreReleaseAsset,
  type GitHubReleaseAsset,
} from '../src/lib/server/github-release';

const asset = (name: string): GitHubReleaseAsset => ({
  name,
  browser_download_url: `https://github.com/emrek0ca/elyan/releases/download/v1.6.8/${name}`,
});

describe('latest release download selection', () => {
  it('normalizes public platform route names', () => {
    expect(normalizePlatform('mac')).toBe('macos');
    expect(normalizePlatform('macos')).toBe('macos');
    expect(normalizePlatform('win')).toBe('windows');
    expect(normalizePlatform('windows')).toBe('windows');
    expect(normalizePlatform('linux')).toBe('linux');
    expect(normalizePlatform('android')).toBeNull();
  });

  it('chooses the Windows installer over portable and checksum assets', () => {
    const picked = pickReleaseAsset([
      asset('Elyan-1.6.8-Windows-x64-portable.zip'),
      asset('Elyan-1.6.8-Windows-x64-Setup.exe.sha256'),
      asset('Elyan-1.6.8-Windows-x64-Setup.exe'),
      asset('Elyan-1.6.8-macOS-arm64.dmg'),
    ], 'windows');

    expect(picked?.name).toBe('Elyan-1.6.8-Windows-x64-Setup.exe');
    expect(scoreReleaseAsset(asset('Elyan-1.6.8-Windows-x64-Setup.exe.sha256'), 'windows')).toBe(-1);
  });

  it('chooses the macOS DMG over the zipped app bundle', () => {
    const picked = pickReleaseAsset([
      asset('Elyan-1.6.8-macOS-arm64.app.zip'),
      asset('Elyan-1.6.8-macOS-arm64.dmg'),
      asset('Elyan-1.6.8-Linux-x64.deb'),
    ], 'macos');

    expect(picked?.name).toBe('Elyan-1.6.8-macOS-arm64.dmg');
  });

  it('chooses the Linux package over the portable archive', () => {
    const picked = pickReleaseAsset([
      asset('Elyan-1.6.8-Linux-x64-portable.tar.gz'),
      asset('Elyan-1.6.8-Linux-x64.deb'),
      asset('Elyan-1.6.8-Windows-x64-Setup.exe'),
    ], 'linux');

    expect(picked?.name).toBe('Elyan-1.6.8-Linux-x64.deb');
  });
});
