import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('en', 'data-deletion');

export default function DeleteAccountAliasPage() {
  return <StaticContentPage locale="en" slug="data-deletion" />;
}
