import type { Metadata } from 'next';
import { notFound } from 'next/navigation';

import { buildMetadata } from '@/lib/metadata';
import { isSiteLocale, locales } from '@/lib/locales';
import { setRequestLocale } from 'next-intl/server';
import { AuthProvider } from '@/components/providers/auth-provider';
import '../globals.css';

export function generateStaticParams() {
  return locales.map((locale) => ({ locale }));
}

export async function generateMetadata({
  params
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  const { locale } = await params;

  if (!isSiteLocale(locale)) {
    return {};
  }

  return buildMetadata(locale);
}

export default async function LocaleLayout({
  children,
  params
}: Readonly<{
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}>) {
  const { locale } = await params;

  if (!isSiteLocale(locale)) {
    notFound();
  }

  setRequestLocale(locale);

  return (
    <>
      <AuthProvider>
        {children}
      </AuthProvider>
    </>
  );
}
