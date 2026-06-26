'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import type { SiteLocale } from '@/lib/locales';

type LocaleSwitchProps = {
  currentLocale: SiteLocale;
  localeLabel: string;
  switchToEnglish: string;
  switchToTurkish: string;
};

export function LocaleSwitch({
  currentLocale,
  localeLabel,
  switchToEnglish,
  switchToTurkish
}: LocaleSwitchProps) {
  const pathname = usePathname();
  const nextLocale = currentLocale === 'tr' ? 'en' : 'tr';
  const normalizedPath =
    pathname.startsWith('/tr') || pathname.startsWith('/en')
      ? pathname.replace(/^\/(tr|en)/, `/${nextLocale}`)
      : `/${nextLocale}`;
  const switchLabel = nextLocale === 'tr' ? switchToTurkish : switchToEnglish;

  return (
    <div className="locale-switch" aria-label={localeLabel}>
      <span aria-hidden="true">{currentLocale.toUpperCase()}</span>
      <Link aria-label={switchLabel} href={normalizedPath}>
        {nextLocale.toUpperCase()}
      </Link>
    </div>
  );
}
