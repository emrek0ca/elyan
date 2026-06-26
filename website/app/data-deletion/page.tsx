import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'data-deletion');

export default function DataDeletionAliasPage() {
  return <StaticContentPage locale="tr" slug="data-deletion" />;
}
