/**
 * Locale normalizer — converts OS locale strings to supported app locale codes.
 * Supported: 'tr', 'en'
 * Default fallback: 'en'
 */

export type SupportedLocale = 'tr' | 'en';

const SUPPORTED: readonly SupportedLocale[] = ['tr', 'en'];

export function normalizeLocale(raw: string | null | undefined): SupportedLocale {
  if (!raw) return 'en';
  const lower = raw.toLowerCase().replace('_', '-');
  // Exact match
  if (lower === 'tr' || lower.startsWith('tr-')) return 'tr';
  if (lower === 'en' || lower.startsWith('en-')) return 'en';
  // Language-only prefix check
  const prefix = lower.split('-')[0] ?? '';
  if (SUPPORTED.includes(prefix as SupportedLocale)) {
    return prefix as SupportedLocale;
  }
  return 'en';
}

/** Read user language preference from localStorage, fallback to OS locale */
export function resolveActiveLocale(systemLocale: string): SupportedLocale {
  try {
    const stored = localStorage.getItem('elyan-language');
    if (stored && SUPPORTED.includes(stored as SupportedLocale)) {
      return stored as SupportedLocale;
    }
  } catch {
    // localStorage unavailable
  }
  return normalizeLocale(systemLocale);
}

/** Persist language selection */
export function saveLocalePreference(locale: SupportedLocale): void {
  try {
    localStorage.setItem('elyan-language', locale);
  } catch {
    // ignore
  }
}

/** Clear language override (revert to system) */
export function clearLocalePreference(): void {
  try {
    localStorage.removeItem('elyan-language');
  } catch {
    // ignore
  }
}

export { SUPPORTED };
