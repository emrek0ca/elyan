import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'support');

export default function SupportAliasPage() {
  return <StaticContentPage locale="tr" slug="support" />;
}
