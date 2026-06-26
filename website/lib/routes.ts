import type { PageKey } from '@/content/site.types';
import { defaultLocale, type SiteLocale } from '@/lib/locales';

export const pageOrder: readonly Exclude<PageKey, 'home'>[] = [
  'desktop',
  'mobile',
  'download',
  'privacy',
  'terms',
  'data-deletion',
  'support',
  'ai'
] as const;

export function localePath(locale: SiteLocale, page: PageKey = 'home'): string {
  if (page === 'home') {
    return `/${locale}`;
  }

  return `/${locale}/${page}`;
}

export function canonicalUrl(locale: SiteLocale, page: PageKey = 'home'): string {
  return `https://elyan.dev${localePath(locale, page)}`;
}

export function alternateLinks(page: PageKey = 'home') {
  return {
    tr: canonicalUrl('tr', page),
    en: canonicalUrl('en', page),
    'x-default': canonicalUrl(defaultLocale, page)
  };
}
