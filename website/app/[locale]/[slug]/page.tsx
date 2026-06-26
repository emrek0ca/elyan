import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { StaticContentPage } from '@/components/static-content-page';
import type { PageKey } from '@/content/site.types';
import { buildMetadata } from '@/lib/metadata';
import { isSiteLocale, locales, type SiteLocale } from '@/lib/locales';
import { pageOrder } from '@/lib/routes';

export function generateStaticParams() {
  return locales.flatMap((locale) => pageOrder.map((slug) => ({ locale, slug })));
}

export async function generateMetadata({
  params
}: {
  params: Promise<{ locale: string; slug: string }>;
}): Promise<Metadata> {
  const { locale, slug } = await params;
  if (!isSiteLocale(locale) || !pageOrder.includes(slug as (typeof pageOrder)[number])) {
    return {};
  }

  return buildMetadata(locale, slug as PageKey);
}

export default async function StaticPage({
  params
}: {
  params: Promise<{ locale: string; slug: string }>;
}) {
  const { locale, slug } = await params;

  if (!isSiteLocale(locale) || !pageOrder.includes(slug as (typeof pageOrder)[number])) {
    notFound();
  }

  const safeLocale = locale as SiteLocale;
  return <StaticContentPage locale={safeLocale} slug={slug as Exclude<PageKey, 'home'>} />;
}
