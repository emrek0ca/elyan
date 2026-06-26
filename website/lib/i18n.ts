import { getRequestConfig } from 'next-intl/server';

import { getSiteContent } from '@/lib/content';
import { defaultLocale, isSiteLocale } from '@/lib/locales';

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = requested && isSiteLocale(requested) ? requested : defaultLocale;
  const content = getSiteContent(locale);

  return {
    locale,
    messages: content.messages
  };
});
