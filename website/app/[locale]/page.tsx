import Link from 'next/link';

import { ParallaxImage } from '@/components/parallax-image';
import { TextReveal } from '@/components/text-reveal';
import { AnimatedBlock } from '@/components/animated-block';
import { SiteShell } from '@/components/site-shell';
import { CommandDemo } from '@/components/command-demo';
import { CapabilityMarquee } from '@/components/capability-marquee';
import { PromptTyper } from '@/components/prompt-typer';
import { getSiteContent } from '@/lib/content';
import { buildMetadata } from '@/lib/metadata';
import { isSiteLocale, type SiteLocale } from '@/lib/locales';
import { canonicalUrl } from '@/lib/routes';
import { setRequestLocale } from 'next-intl/server';

// New Waow Components
import { MagneticButton } from '@/components/magnetic-button';
import { BentoGrid, BentoCard } from '@/components/bento-grid';
import { KineticFabric } from '@/components/kinetic-fabric';
import { ScrollPath } from '@/components/scroll-path';
import { VelocityScroll } from '@/components/velocity-scroll';

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
  const isEnglish = safeLocale === 'en';

  return (
    <SiteShell locale={safeLocale}>
      <ScrollPath className="z-0 mix-blend-difference" />
      
      <section className="home-hero relative z-10" aria-labelledby="home-title">
        <KineticFabric className="absolute top-[-10%] left-[50%] w-[100vw] -translate-x-1/2 h-[120%] -z-10 overflow-hidden flex flex-col group cursor-crosshair select-none opacity-40 mix-blend-screen pointer-events-auto" />
        <AnimatedBlock className="home-hero__copy">
          <span className="eyebrow">{home.eyebrow}</span>
          <TextReveal as="h1" id="home-title" text={home.title} className="home-hero__title" />
          <p className="home-hero__lede">{home.description}</p>
          <div className="home-hero__actions">
            {home.ctas.map((item, index) => (
              index === 0 ? (
                <MagneticButton
                  key={item.href}
                  as="link"
                  href={item.href}
                  className="btn btn--primary"
                >
                  {item.label}
                </MagneticButton>
              ) : (
                <MagneticButton
                  key={item.href}
                  as="link"
                  href={item.href}
                  className="btn btn--ghost"
                >
                  {item.label}
                </MagneticButton>
              )
            ))}
          </div>
        </AnimatedBlock>

        <AnimatedBlock className="home-hero__visual" delay={0.12}>
          <figure className="home-hero__frame">
            <ParallaxImage src="/desk_focus.png" alt="Elyan" priority />
            <PromptTyper locale={safeLocale} />
          </figure>
        </AnimatedBlock>
      </section>

      <section className="home-marquee relative z-10" aria-label={isEnglish ? 'What Elyan can do' : 'Elyan neler yapabilir'}>
        <span className="eyebrow">{isEnglish ? 'What Elyan can do' : 'Elyan neler yapabilir'}</span>
        <CapabilityMarquee locale={safeLocale} />
      </section>

      {/* Cinematic Velocity Scroll Background */}
      <div className="relative w-full py-12 md:py-24 -my-12 z-0 opacity-5 pointer-events-none overflow-hidden">
        <VelocityScroll text={home.systemWidgets?.velocityText || 'AUTONOMOUS • LOCAL • SECURE • '} className="font-display text-[8rem] md:text-[14rem] tracking-tighter text-[var(--text)]" />
      </div>

      <section className="home-value relative z-10" aria-labelledby="value-title">
        <AnimatedBlock className="home-value__head">
          <TextReveal as="h2" id="value-title" text={home.boundaryTitle} className="section-title" />
          <p className="home-value__lede">{home.intro}</p>
        </AnimatedBlock>
        
        {/* Replaced static list with 3D Bento Grid */}
        <BentoGrid className="mt-12 md:mt-20">
          {home.boundaryCopy.map((item, index) => (
            <BentoCard
              key={item.title}
              title={item.title}
              description={item.body}
              delay={index * 0.1}
              header={
                <div className="w-12 h-12 rounded-2xl bg-[var(--surface-2)] border border-[var(--outline)] flex items-center justify-center font-mono text-[var(--secondary)] font-bold text-lg shadow-inner">
                  {String(index + 1).padStart(2, '0')}
                </div>
              }
            />
          ))}
        </BentoGrid>
      </section>



      <section className="home-flow relative z-10" aria-labelledby="flow-title">
        <div className="home-flow__grid">
          <AnimatedBlock className="home-flow__head">
            <span className="eyebrow">{site.messages.ui.controlLoopTitle}</span>
            <h2 id="flow-title" className="section-title">{home.loopTitle}</h2>
            <ol className="home-flow__steps">
              {home.loopSteps.map((step, index) => (
                <li key={step.title}>
                  <span className="home-flow__step-index">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{step.title}</h3>
                    <p>{step.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </AnimatedBlock>
          <AnimatedBlock className="home-flow__demo" delay={0.1}>
            <CommandDemo locale={safeLocale} />
          </AnimatedBlock>
        </div>
      </section>

      <section className="home-cta relative z-10" aria-labelledby="cta-title">
        <div className="home-cta__image" aria-hidden="true">
          <ParallaxImage src="/cozy_night.png" alt="" />
        </div>
        <AnimatedBlock className="home-cta__copy">
          <span className="eyebrow">{site.messages.ui.finalCtaLabel}</span>
          <TextReveal as="h2" id="cta-title" text={home.finalTitle} className="home-cta__title" />
          <p className="home-cta__lede">{home.finalCopy}</p>
          <div className="home-cta__actions">
            {home.finalLinks.map((item, index) => (
              index === 0 ? (
                <MagneticButton
                  key={item.href}
                  as="link"
                  href={item.href}
                  className="btn btn--primary"
                >
                  {item.label}
                </MagneticButton>
              ) : (
                <MagneticButton
                  key={item.href}
                  as="link"
                  href={item.href}
                  className="btn btn--ghost"
                >
                  {item.label}
                </MagneticButton>
              )
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
