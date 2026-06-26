import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'mobile');

export default function MobileAliasPage() {
  return <StaticContentPage locale="tr" slug="mobile" />;
}
