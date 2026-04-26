'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Sidebar } from './Sidebar';

function isRuntimeRoute(pathname: string) {
  return pathname.startsWith('/chat') || pathname.startsWith('/preview/chat') || pathname.startsWith('/manage');
}

export function MainLayoutClient({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (isRuntimeRoute(pathname)) {
    return (
      <div className="app-shell">
        <Sidebar />
        <main className="main-content">
          <div className="main-content__inner">{children}</div>
        </main>
      </div>
    );
  }

  return (
    <div className="site-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <header className="site-header">
        <div className="site-header__inner">
          <Link href="/" className="site-brand">
            <span className="site-brand__mark">E</span>
            <span className="site-brand__meta">
              <strong>Elyan</strong>
              <span>Local control panel</span>
            </span>
          </Link>

          <div className="site-header__actions">
            <Link href="/manage" className={pathname.startsWith('/manage') ? 'site-nav__link site-nav__link--active' : 'site-nav__link'}>
              Manage
            </Link>
            <Link href="/chat/new" className="site-header__button">
              Chat
            </Link>
          </div>
        </div>
      </header>

      <main id="main-content" className="site-main">
        {children}
      </main>

      <footer className="site-footer">
        <div className="site-footer__inner">
          <div className="site-footer__brand">
            <strong>Elyan</strong>
            <p>Local runtime console for settings, channels, models, and routing.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
