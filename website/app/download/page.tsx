import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'download');

export default function DownloadAliasPage() {
  return <StaticContentPage locale="tr" slug="download" />;
}
