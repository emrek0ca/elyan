export const locales = ['tr', 'en'] as const;

export type SiteLocale = (typeof locales)[number];

export const defaultLocale: SiteLocale = 'tr';

export function isSiteLocale(value: string): value is SiteLocale {
  return locales.includes(value as SiteLocale);
}
