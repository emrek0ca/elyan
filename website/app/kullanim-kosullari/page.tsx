import { StaticContentPage } from '@/components/static-content-page';
import { buildMetadata } from '@/lib/metadata';

export const metadata = buildMetadata('tr', 'terms');

export default function KullanimKosullariPage() {
  return <StaticContentPage locale="tr" slug="terms" />;
}
