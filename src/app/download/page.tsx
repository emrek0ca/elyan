import { DownloadSurface } from '@/components/download/DownloadSurface';
import { getLatestElyanReleaseResponse } from '@/core/control-plane/releases';

export const dynamic = 'force-dynamic';

export default async function DownloadPage() {
  const release = await getLatestElyanReleaseResponse().catch(() => null);

  return <DownloadSurface release={release} />;
}
