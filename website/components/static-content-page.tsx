import Link from 'next/link';

import { AnimatedBlock } from '@/components/animated-block';
import { ParallaxImage } from '@/components/parallax-image';
import { TextReveal } from '@/components/text-reveal';
import { ScreenshotCarousel } from '@/components/screenshot-carousel';
import { SiteShell } from '@/components/site-shell';
import type { PageKey } from '@/content/site.types';
import { getPageContent, getSiteContent } from '@/lib/content';
import type { SiteLocale } from '@/lib/locales';

type StaticPageKey = Exclude<PageKey, 'home'>;

function extractEffectiveDate(intro: string) {
  const match = intro.match(/(?:Yürürlük tarihi|Effective date):\s*([^.]*)\./i);
  return match?.[1]?.trim() || null;
}

function cleanLegalTitle(title: string) {
  return title.replace(/^\d+\.\s*/, '');
}

export function StaticContentPage({
  locale,
  slug
}: {
  locale: SiteLocale;
  slug: StaticPageKey;
}) {
  const page = getPageContent(locale, slug);
  const site = getSiteContent(locale);
  const effectiveDate = extractEffectiveDate(page.intro);
  const legalSections =
    page.legal?.map((section) => ({
      title: section.title,
      body: section.body
    })) ??
    (slug === 'data-deletion'
      ? page.sections.map((section, index) => ({
          title: `${index + 1}. ${section.title}`,
          body: [section.body]
        }))
      : []);

  if (legalSections.length) {
    return (
      <SiteShell locale={locale}>
        <section className="legal-document-shell" aria-labelledby="legal-document-title">
          <AnimatedBlock className="legal-document-paper">
            <header className="legal-document-header">
              <div className="legal-document-kicker">
                <span>{page.eyebrow}</span>
                <span>{locale === 'tr' ? 'Resmi belge' : 'Official document'}</span>
                <span>{effectiveDate ? `${locale === 'tr' ? 'Yururluk' : 'Effective'} ${effectiveDate}` : 'V1'}</span>
              </div>
              <h1 id="legal-document-title">{page.title}</h1>
              <p>{page.intro}</p>
            </header>

            <div className="legal-document-body">
              {legalSections.map((section, index) => (
                <section className="legal-document-section" key={section.title}>
                  <div className="legal-document-section__number">{String(index + 1).padStart(2, '0')}</div>
                  <div className="legal-document-section__content">
                    <h2>{cleanLegalTitle(section.title)}</h2>
                    {section.body.map((paragraph) => (
                      <p key={paragraph}>{paragraph}</p>
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </AnimatedBlock>
        </section>

        <section className="subfooter-links">
          <Link className="pill-link pill-link--soft" href={`/${locale}`}>
            {site.messages.ui.backHome}
          </Link>
        </section>
      </SiteShell>
    );
  }

  return (
    <SiteShell locale={locale}>
      <section className="page-hero relative overflow-hidden min-h-[50vh] flex flex-col justify-end">
        {page.heroImage && (
          <div className="absolute inset-0 z-0" style={{ maskImage: 'linear-gradient(to bottom, black 40%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to bottom, black 40%, transparent 100%)' }}>
            <ParallaxImage src={page.heroImage} alt={page.title} priority />
            <div className="absolute inset-0 bg-gradient-to-t from-[var(--background)] via-[var(--background-deep)]/80 to-[var(--background)]/20"></div>
          </div>
        )}
        <AnimatedBlock className="page-hero__copy relative z-10">
          <span className="eyebrow">{page.eyebrow}</span>
          <TextReveal as="h1" text={page.title} delay={0.1} />
          <TextReveal as="p" text={page.intro} className="lede" delay={0.4} wordDelay={0.015} />
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
        <section className="content-section">
          <div className="stack-grid">
            {page.sections.map((section, index) => (
              <AnimatedBlock className="surface-row" delay={index * 0.05} key={section.title}>
                <div>
                  <h3>{section.title}</h3>
                  <p>{section.body}</p>
                </div>
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
