import { AppComingSoon } from '@/components/app-coming-soon';

export default async function LoginPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;

  return <AppComingSoon locale={locale} />;
}
