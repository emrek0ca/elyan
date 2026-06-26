import siteEn from '@/content/site.en';
import siteTr from '@/content/site.tr';
import type { PageKey, SiteContent } from '@/content/site.types';
import { defaultLocale, isSiteLocale, type SiteLocale } from '@/lib/locales';

const contentByLocale: Record<SiteLocale, SiteContent> = {
  tr: siteTr,
  en: siteEn
};

export function getSiteContent(locale: string): SiteContent {
  if (isSiteLocale(locale)) {
    return contentByLocale[locale];
  }

  return contentByLocale[defaultLocale];
}

export function getPageContent(locale: string, page: Exclude<PageKey, 'home'>) {
  return getSiteContent(locale).pages[page];
}
