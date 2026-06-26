import type { MetadataRoute } from 'next';

import { locales } from '@/lib/locales';
import { pageOrder } from '@/lib/routes';

export const dynamic = 'force-static';

export default function sitemap(): MetadataRoute.Sitemap {
  return locales.flatMap((locale) => [
    {
      url: `https://elyan.dev/${locale}`
    },
    ...pageOrder.map((page) => ({
      url: `https://elyan.dev/${locale}/${page}`
    }))
  ]);
}
