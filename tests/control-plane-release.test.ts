import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  getLatestElyanReleaseResponse,
  getLatestElyanReleaseSnapshot,
} from '@/core/control-plane/releases';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('release resolver', () => {
  it('selects the latest publishable GitHub release with all required assets', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            tag_name: 'v1.2.0',
            name: 'v1.2.0',
            html_url: 'https://github.com/elyan-dev/elyan/releases/tag/v1.2.0',
            url: 'https://api.github.com/repos/elyan-dev/elyan/releases/1',
            draft: false,
            prerelease: false,
            published_at: '2026-04-20T10:00:00Z',
            assets: [
              {
                name: 'elyan-macos-arm64.zip',
                size: 10,
                browser_download_url: 'https://example.com/macos-arm64.zip',
              },
              {
                name: 'elyan-macos-x64.zip',
                size: 10,
                browser_download_url: 'https://example.com/macos-x64.zip',
              },
            ],
          },
          {
            tag_name: 'v1.1.0',
            name: 'v1.1.0',
            html_url: 'https://github.com/elyan-dev/elyan/releases/tag/v1.1.0',
            url: 'https://api.github.com/repos/elyan-dev/elyan/releases/2',
            draft: false,
            prerelease: false,
            published_at: '2026-04-19T10:00:00Z',
            assets: [
              {
                name: 'elyan-macos-arm64.zip',
                size: 10,
                browser_download_url: 'https://example.com/macos-arm64.zip',
              },
              {
                name: 'elyan-macos-x64.zip',
                size: 10,
                browser_download_url: 'https://example.com/macos-x64.zip',
              },
              {
                name: 'elyan-linux-x64.tar.gz',
                size: 10,
                browser_download_url: 'https://example.com/linux.tar.gz',
              },
              {
                name: 'elyan-windows-x64.zip',
                size: 10,
                browser_download_url: 'https://example.com/windows.zip',
              },
            ],
          },
        ],
      })
    );

    const release = await getLatestElyanReleaseSnapshot();

    expect(release?.tagName).toBe('v1.1.0');
    expect(release?.complete).toBe(true);
    expect(release?.assets).toHaveLength(4);
  });

  it('reports update availability for the installed CLI and hosted panel', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            tag_name: 'v1.1.0',
            name: 'v1.1.0',
            html_url: 'https://github.com/elyan-dev/elyan/releases/tag/v1.1.0',
            url: 'https://api.github.com/repos/elyan-dev/elyan/releases/1',
            draft: false,
            prerelease: false,
            published_at: '2026-04-20T10:00:00Z',
            assets: [
              {
                name: 'elyan-macos-arm64.zip',
                size: 10,
                browser_download_url: 'https://example.com/macos-arm64.zip',
              },
              {
                name: 'elyan-macos-x64.zip',
                size: 10,
                browser_download_url: 'https://example.com/macos-x64.zip',
              },
              {
                name: 'elyan-linux-x64.tar.gz',
                size: 10,
                browser_download_url: 'https://example.com/linux.tar.gz',
              },
              {
                name: 'elyan-windows-x64.zip',
                size: 10,
                browser_download_url: 'https://example.com/windows.zip',
              },
            ],
          },
        ],
      })
    );

    const response = await getLatestElyanReleaseResponse();

    expect(response.currentVersion).toBe('1.0.0');
    expect(response.currentTagName).toBe('v1.0.0');
    expect(response.updateAvailable).toBe(true);
    expect(response.updateStatus).toBe('update_available');
    expect(response.latest?.tagName).toBe('v1.1.0');
    expect(response.updateMessage).toContain('v1.1.0');
  });

  it('fails closed when no publishable release is available', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => [
          {
            tag_name: 'v1.2.0-beta.1',
            name: 'v1.2.0-beta.1',
            html_url: 'https://github.com/elyan-dev/elyan/releases/tag/v1.2.0-beta.1',
            url: 'https://api.github.com/repos/elyan-dev/elyan/releases/1',
            draft: false,
            prerelease: true,
            published_at: '2026-04-20T10:00:00Z',
            assets: [],
          },
        ],
      })
    );

    const response = await getLatestElyanReleaseResponse();

    expect(response.publishable).toBe(false);
    expect(response.latest).toBeNull();
    expect(response.updateStatus).toBe('unavailable');
    expect(response.updateAvailable).toBe(false);
    expect(response.updateMessage).toContain('No publishable release');
  });
});
