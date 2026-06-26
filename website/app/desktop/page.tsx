import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'desktop');

export default function DesktopAliasPage() {
  return <StaticContentPage locale="tr" slug="desktop" />;
}
