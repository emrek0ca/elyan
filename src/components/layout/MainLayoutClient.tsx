'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { Sidebar } from './Sidebar';

const publicNavigation = [
  { href: '/', label: 'Home' },
  { href: '/platform', label: 'Platform' },
  { href: '/docs', label: 'Docs' },
  { href: '/download', label: 'Download' },
  { href: '/pricing', label: 'Pricing' },
  { href: '/about', label: 'About' },
  { href: '/auth', label: 'Account' },
];

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
              <span>Local-first personal agent</span>
            </span>
          </Link>

          <nav className="site-nav" aria-label="Primary">
            {publicNavigation.map((entry) => {
              const active = pathname === entry.href || (entry.href !== '/' && pathname.startsWith(entry.href));
              return (
                <Link
                  key={entry.href}
                  href={entry.href}
                  className={active ? 'site-nav__link site-nav__link--active' : 'site-nav__link'}
                >
                  {entry.label}
                </Link>
              );
            })}
          </nav>

          <div className="site-header__actions">
            <Link href="/panel" className="site-header__link">
              Panel
            </Link>
            <Link href="/download" className="site-header__button">
              Get Elyan
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
            <p>Official website, docs, hosted account surface, and local-first install guidance.</p>
          </div>

          <div className="site-footer__links">
            <Link href="/docs">Docs</Link>
            <Link href="/download">Install</Link>
            <Link href="/pricing">Pricing</Link>
            <Link href="/about">About</Link>
            <Link href="/auth">Account</Link>
            <Link href="/contact">Contact</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
