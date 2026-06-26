import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'ai');

export default function AiAliasPage() {
  return <StaticContentPage locale="tr" slug="ai" />;
}
