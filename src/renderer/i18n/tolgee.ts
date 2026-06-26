import { Tolgee, FormatSimple, type TolgeeInstance } from '@tolgee/react';
import en from './locales/en.json';
import tr from './locales/tr.json';
import { resolveActiveLocale } from './locale';
import type { SupportedLocale } from './locale';

const STATIC_DATA: Record<string, typeof en> = { en, tr };

let _tolgeeInstance: TolgeeInstance | null = null;
let _currentLocale: SupportedLocale = 'en';

export function getInitialLocale(systemLocale: string): SupportedLocale {
  return resolveActiveLocale(systemLocale);
}

export function createTolgeeInstance(initialLocale: SupportedLocale) {
  _currentLocale = initialLocale;

  _tolgeeInstance = Tolgee()
    .use(FormatSimple())
    .init({
      language: initialLocale,
      fallbackLanguage: 'en',
      staticData: STATIC_DATA,
    });

  return _tolgeeInstance;
}

export function getTolgeeInstance() {
  return _tolgeeInstance;
}

export function getCurrentLocale(): SupportedLocale {
  return _currentLocale;
}

export async function changeLanguage(locale: SupportedLocale): Promise<void> {
  if (!_tolgeeInstance) return;
  _currentLocale = locale;
  await _tolgeeInstance.changeLanguage(locale);
}
