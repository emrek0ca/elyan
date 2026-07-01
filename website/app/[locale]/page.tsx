import Link from 'next/link';

import { AnimatedBlock } from '@/components/animated-block';
import { SiteShell } from '@/components/site-shell';
import { ScrollSequence } from '@/components/scroll-sequence';
import { getSiteContent } from '@/lib/content';
import { buildMetadata } from '@/lib/metadata';
import { isSiteLocale, type SiteLocale } from '@/lib/locales';
import { canonicalUrl } from '@/lib/routes';
import { setRequestLocale } from 'next-intl/server';

export async function generateMetadata({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;

  if (!isSiteLocale(locale)) {
    return {};
  }

  return buildMetadata(locale);
}

export default async function HomePage({
  params
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const safeLocale: SiteLocale = isSiteLocale(locale) ? locale : 'tr';
  
  setRequestLocale(safeLocale);

  const site = getSiteContent(safeLocale);
  const home = site.home;

  return (
    <SiteShell locale={safeLocale}>
      
      {/* Hero & Scroll Sequence */}
      <section className="w-full mb-16">
        <ScrollSequence 
          title={home.title} 
          subtitle={home.eyebrow} 
        />
      </section>

      {/* Intro Text */}
      <section className="content-section text-center max-w-4xl mx-auto mb-24">
        <AnimatedBlock>
          <p className="lede text-2xl md:text-3xl font-medium" style={{ color: 'var(--text)', maxWidth: '100%' }}>
            {home.intro}
          </p>
          <div className="hero-actions justify-center mt-10">
            {home.ctas.map((item, index) => (
              <Link
                className={index === 0 ? 'pill-link pill-link--primary' : 'pill-link pill-link--soft'}
                href={item.href}
                key={item.href}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </AnimatedBlock>
      </section>

      {/* Features Grid */}
      <section className="content-section">
        <AnimatedBlock>
          <span className="eyebrow">{site.messages.ui.controlLoopTitle}</span>
          <h2>{home.loopTitle}</h2>
        </AnimatedBlock>
        <div className="feature-grid mt-6">
          {home.loopSteps.map((step, index) => (
            <AnimatedBlock className="surface-card h-full" delay={index * 0.05} key={step.title}>
              {step.label && <span className="surface-card__label">{step.label}</span>}
              <span className="surface-card__index mb-3 block text-[var(--secondary)]">0{index + 1}</span>
              <h3>{step.title}</h3>
              <p>{step.body}</p>
              {step.pill && <span className="surface-card__pill">{step.pill}</span>}
            </AnimatedBlock>
          ))}
        </div>
      </section>

      {/* Legal & Boundaries */}
      <section className="content-section mt-32">
        <AnimatedBlock>
          <span className="eyebrow">{site.messages.ui.legalTitle}</span>
          <h2>{home.boundaryTitle}</h2>
        </AnimatedBlock>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mt-6">
          {home.boundaryCopy.map((item, index) => (
            <AnimatedBlock 
              className={`surface-card h-full ${index === 0 ? 'md:col-span-2 lg:col-span-1' : ''}`}
              delay={index * 0.05} 
              key={item.title}
            >
              {item.label && <span className="surface-card__label">{item.label}</span>}
              <h3>{item.title}</h3>
              <p>{item.body}</p>
              {item.pill && <span className="surface-card__pill">{item.pill}</span>}
            </AnimatedBlock>
          ))}
        </div>
      </section>

      {/* Use Cases */}
      <section className="content-section mt-32">
        <AnimatedBlock>
          <h2>{home.useCasesTitle}</h2>
        </AnimatedBlock>
        <div className="feature-grid mt-6">
          {home.useCases.map((step, index) => (
            <AnimatedBlock className="surface-card h-full" delay={index * 0.05} key={step.title}>
              {step.label && <span className="surface-card__label">{step.label}</span>}
              <h3>{step.title}</h3>
              <p>{step.body}</p>
              {step.pill && <span className="surface-card__pill">{step.pill}</span>}
            </AnimatedBlock>
          ))}
        </div>
      </section>

      {/* Plans */}
      <section className="content-section mt-32">
        <AnimatedBlock>
          <h2>{home.plansTitle}</h2>
        </AnimatedBlock>
        <div className="feature-grid mt-6">
          {home.plans.map((plan, index) => (
            <AnimatedBlock className="surface-card h-full" delay={index * 0.05} key={plan.title}>
              {plan.label && <span className="surface-card__label">{plan.label}</span>}
              <h3>{plan.title}</h3>
              <p>{plan.body}</p>
              {plan.pill && <span className="surface-card__pill">{plan.pill}</span>}
            </AnimatedBlock>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="cta-section text-center py-20 mt-16 border-t border-[var(--outline)]">
        <AnimatedBlock className="cta-card max-w-2xl mx-auto">
          <span className="eyebrow">{site.messages.ui.finalCtaLabel}</span>
          <h2 style={{ fontSize: 'clamp(36px, 5vw, 56px)' }}>{home.finalTitle}</h2>
          <p className="lede mx-auto mb-8">{home.finalCopy}</p>
          <div className="hero-actions justify-center">
            {home.finalLinks.map((item, index) => (
              <Link
                className={index === 0 ? 'pill-link pill-link--primary' : 'pill-link pill-link--soft'}
                href={item.href}
                key={item.href}
              >
                {item.label}
              </Link>
            ))}
          </div>
        </AnimatedBlock>
      </section>

      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            '@context': 'https://schema.org',
            '@type': 'SoftwareApplication',
            name: site.siteName,
            applicationCategory: 'BusinessApplication',
            operatingSystem: 'macOS, Windows, Linux, iOS, Android',
            url: canonicalUrl(safeLocale),
            description: site.siteDescription
          })
        }}
      />
    </SiteShell>
  );
}
