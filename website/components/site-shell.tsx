import Link from 'next/link';
import type { PropsWithChildren } from 'react';

import { LocaleSwitch } from '@/components/locale-switch';
import { getSiteContent } from '@/lib/content';
import type { SiteLocale } from '@/lib/locales';

type SiteShellProps = PropsWithChildren<{
  locale: SiteLocale;
}>;

export async function SiteShell({ locale, children }: SiteShellProps) {
  const site = getSiteContent(locale);
  const ui = site.messages.ui;

  return (
    <div className="page-shell">
      <div className="page-grid">
        <header className="topbar">
          <Link aria-label={site.siteName} className="brand-lockup" href={`/${locale}`}>
            <img alt="" height="28" src="/brand/logo.png" width="28" />
          </Link>
          <nav aria-label={ui.primaryNavigationLabel} className="topnav">
            {site.nav.map((item) => (
              <Link href={item.href} key={item.href}>
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="topbar__actions text-sm md:text-base">
            <LocaleSwitch
              currentLocale={locale}
              localeLabel={ui.localeLabel}
              switchToEnglish={ui.switchToEnglish}
              switchToTurkish={ui.switchToTurkish}
            />
          </div>
        </header>
        <main>{children}</main>
        <footer className="footer">
          <div className="footer__note">
            <p>{site.footer.note}</p>
          </div>
          <div className="footer__links">
            <div>
              <span className="footer__heading">{ui.footerLegalLabel}</span>
              {site.footer.legal.map((item) => (
                <Link href={item.href} key={item.href}>
                  {item.label}
                </Link>
              ))}
            </div>
            <div>
              <span className="footer__heading">{ui.footerSupportLabel}</span>
              {site.footer.support.map((item) => (
                <Link href={item.href} key={item.href}>
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
