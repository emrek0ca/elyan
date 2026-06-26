import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'privacy');

export default function PrivacyAliasPage() {
  return <StaticContentPage locale="tr" slug="privacy" />;
}
