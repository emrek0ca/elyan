import type { Metadata } from 'next';

import type { PageKey } from '@/content/site.types';
import { getPageContent, getSiteContent } from '@/lib/content';
import type { SiteLocale } from '@/lib/locales';
import { alternateLinks, canonicalUrl } from '@/lib/routes';

export function buildMetadata(locale: SiteLocale, page: PageKey = 'home'): Metadata {
  const site = getSiteContent(locale);
  const pageContent = page === 'home' ? site.home : getPageContent(locale, page);
  const title = page === 'home' ? site.siteTitle : `Elyan | ${pageContent.title}`;
  const description =
    page === 'home' ? site.siteDescription : pageContent.description;

  return {
    title,
    description,
    applicationName: site.siteName,
    metadataBase: new URL('https://elyan.dev'),
    alternates: {
      canonical: canonicalUrl(locale, page),
      languages: alternateLinks(page)
    },
    openGraph: {
      title,
      description,
      url: canonicalUrl(locale, page),
      siteName: site.siteName,
      locale,
      type: 'website',
      images: [
        {
          url: 'https://elyan.dev/og-elyan-website.svg',
          width: 1200,
          height: 630,
          alt: title
        }
      ]
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
      images: ['https://elyan.dev/og-elyan-website.svg']
    }
  };
}
