import type { APIRoute } from 'astro';
import {
  fetchLatestElyanRelease,
  normalizePlatform,
  pickReleaseAsset,
} from '../../lib/server/github-release';

export const prerender = false;

export const GET: APIRoute = async ({ params }) => {
  const platform = normalizePlatform(params.platform);
  if (!platform) {
    return new Response('Unsupported platform', {
      status: 404,
      headers: { 'Cache-Control': 'no-store' },
    });
  }

  try {
    const release = await fetchLatestElyanRelease();
    const asset = pickReleaseAsset(Array.isArray(release.assets) ? release.assets : [], platform);

    if (!asset?.browser_download_url || !asset.name) {
      return new Response('No release asset found', {
        status: 404,
        headers: { 'Cache-Control': 'no-store' },
      });
    }

    return new Response(null, {
      status: 302,
      headers: {
        Location: asset.browser_download_url,
        'Cache-Control': 'no-store',
        'X-Elyan-Release': release.tag_name ?? 'latest',
        'X-Elyan-Asset': asset.name,
      },
    });
  } catch {
    return new Response('Release lookup failed', {
      status: 502,
      headers: { 'Cache-Control': 'no-store' },
    });
  }
};
