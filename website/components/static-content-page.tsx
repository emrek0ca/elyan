import Link from 'next/link';

import { AnimatedBlock } from '@/components/animated-block';
import { ScreenshotCarousel } from '@/components/screenshot-carousel';
import { SiteShell } from '@/components/site-shell';
import type { PageKey } from '@/content/site.types';
import { getPageContent, getSiteContent } from '@/lib/content';
import type { SiteLocale } from '@/lib/locales';

type StaticPageKey = Exclude<PageKey, 'home'>;

export function StaticContentPage({
  locale,
  slug
}: {
  locale: SiteLocale;
  slug: StaticPageKey;
}) {
  const page = getPageContent(locale, slug);
  const site = getSiteContent(locale);

  return (
    <SiteShell locale={locale}>
      <section className="page-hero">
        <AnimatedBlock className="page-hero__copy">
          <span className="eyebrow">{page.eyebrow}</span>
          <h1>{page.title}</h1>
          <p className="lede">{page.intro}</p>
          {page.ctas?.length ? (
            <div className="hero-actions">
              {page.ctas.map((item, index) => (
                <Link
                  className={index === 0 ? 'pill-link pill-link--primary' : 'pill-link pill-link--soft'}
                  href={item.href}
                  key={item.href}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          ) : null}
        </AnimatedBlock>
        {page.visual ? (
          <AnimatedBlock className="page-hero__visual" delay={0.08}>
            <ScreenshotCarousel
              items={page.visual.screenshots}
              label={site.messages.ui.screenshotLabel}
              nextLabel={site.messages.ui.nextScreenshot}
              previousLabel={site.messages.ui.previousScreenshot}
            />
          </AnimatedBlock>
        ) : null}
      </section>

      {page.sections.length ? (
        <section className="content-section mt-16">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-6">
            {page.sections.map((section, index) => (
              <AnimatedBlock 
                className={`surface-card h-full ${index === 0 && page.sections.length === 3 ? 'md:col-span-2 lg:col-span-1' : ''}`}
                delay={index * 0.05} 
                key={section.title}
              >
                {section.label && <span className="surface-card__label">{section.label}</span>}
                <h3>{section.title}</h3>
                <p>{section.body}</p>
                {section.pill && <span className="surface-card__pill">{section.pill}</span>}
              </AnimatedBlock>
            ))}
          </div>
        </section>
      ) : null}

      {page.legal?.length ? (
        <section className="content-section">
          <div className="legal-grid">
            {page.legal.map((section, index) => (
              <AnimatedBlock className="surface-card" delay={index * 0.05} key={section.title}>
                <h3>{section.title}</h3>
                <div className="legal-copy">
                  {section.body.map((paragraph) => (
                    <p key={paragraph}>{paragraph}</p>
                  ))}
                </div>
              </AnimatedBlock>
            ))}
          </div>
        </section>
      ) : null}

      <section className="subfooter-links">
        <Link className="pill-link pill-link--soft" href={`/${locale}`}>
          {site.messages.ui.backHome}
        </Link>
      </section>
    </SiteShell>
  );
}
