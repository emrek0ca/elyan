import Link from 'next/link';

import Image from 'next/image';
import { ParallaxImage } from '@/components/parallax-image';
import { TextReveal } from '@/components/text-reveal';
import { AnimatedBlock } from '@/components/animated-block';
import { SiteShell } from '@/components/site-shell';
import { VelocityScroll } from '@/components/velocity-scroll';
import { StickyScroll } from '@/components/sticky-scroll';
import { BentoGrid, BentoCard } from '@/components/bento-grid';
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
      
      {/* Cinematic Hero */}
      <section className="home-hero">
        <div className="absolute top-[20%] left-0 w-full opacity-5 pointer-events-none z-0">
          <VelocityScroll text="ELYAN • " defaultVelocity={1.5} className="text-[10rem] md:text-[16rem] font-bold text-[var(--foreground)] tracking-tighter" />
        </div>
        
        <div className="absolute inset-0 z-0 opacity-80 mix-blend-luminosity" style={{ maskImage: 'linear-gradient(to bottom, black 40%, transparent 100%)', WebkitMaskImage: 'linear-gradient(to bottom, black 40%, transparent 100%)' }}>
          <ParallaxImage
            src="/hero_cafe.png"
            alt="Elyan Hero"
            priority
          />
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-[var(--background)] via-[var(--background-deep)]/90 to-[var(--background)]/40 z-0"></div>
        <div className="absolute inset-0 bg-gradient-to-r from-[var(--background)]/80 to-transparent z-0"></div>
        
        <AnimatedBlock className="relative z-10 max-w-4xl mx-auto w-full pt-20">
          <span className="text-sm md:text-base font-semibold tracking-wider uppercase mb-6 block text-[var(--text-muted)]">
            {home.eyebrow}
          </span>
          <TextReveal 
            as="h1" 
            text={home.title} 
            className="text-5xl md:text-7xl font-bold tracking-tight text-[var(--text)] mb-6 balanced"
            delay={0.2}
          />
          <TextReveal 
            as="p" 
            text={home.description} 
            className="text-xl md:text-3xl text-[var(--text-muted)] font-medium max-w-2xl"
            delay={0.6}
            wordDelay={0.015}
          />
        </AnimatedBlock>
      </section>

      {/* Intro + CTAs */}
      <section className="home-intro-section overflow-visible">
        <AnimatedBlock className="home-intro-inner relative">
          <div className="relative w-full aspect-[4/3] md:aspect-[3/4] rounded-2xl shadow-2xl z-10">
            <div className="absolute inset-0 rounded-2xl overflow-hidden">
              <ParallaxImage
                src="/desk_focus.png"
                alt="Elyan focused"
              />
            </div>
          </div>
          <div className="home-intro-copy relative z-10">
            <TextReveal 
              as="p"
              text={home.intro} 
              className="home-intro-text"
            />
            <div className="hero-actions home-intro-actions">
              {home.ctas.map((item, index) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={index === 0 ? 'home-cta-primary' : 'home-cta-secondary'}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          </div>
        </AnimatedBlock>
      </section>

      {/* Feature Loop Steps */}
      <section className="relative overflow-visible pb-20">
        <StickyScroll 
          content={home.loopSteps.map((step) => ({
            title: step.title,
            description: step.body,
            image: step.image
          }))} 
        />
      </section>

      {/* Boundary / Legal section */}
      <section className="content-section">
        <BentoGrid>
          {home.boundaryCopy.map((item, index) => (
            <BentoCard 
              key={item.title}
              title={item.title}
              description={item.body}
              delay={index * 0.1}
              className={index === 0 ? "md:col-span-2" : index === 3 ? "md:col-span-2" : ""}
            />
          ))}
        </BentoGrid>
      </section>

      {/* Final CTA */}
      <section className="relative min-h-[80vh] flex items-center justify-center overflow-hidden w-full py-32">
        <div className="absolute inset-0 z-0 opacity-40 mix-blend-luminosity" style={{ maskImage: 'radial-gradient(circle at center, black 0%, transparent 70%)', WebkitMaskImage: 'radial-gradient(circle at center, black 0%, transparent 70%)' }}>
          <ParallaxImage
            src="/cozy_night.png"
            alt="Elyan night CTA"
          />
        </div>
        <AnimatedBlock className="relative z-10 max-w-5xl mx-auto text-center px-4 flex flex-col items-center">
          <TextReveal 
            as="h2"
            text={home.finalTitle}
            className="text-6xl md:text-8xl font-medium tracking-tight mb-8 text-[var(--foreground)]"
          />
          <p className="text-xl md:text-3xl text-[var(--foreground)]/70 font-light mb-16 max-w-3xl leading-relaxed">{home.finalCopy}</p>
          <div className="flex flex-wrap items-center justify-center gap-6">
            {home.finalLinks.map((item, index) => (
              <Link
                key={item.href}
                href={item.href}
                className={index === 0 ? 'home-cta-primary text-xl px-10 py-5 rounded-full shadow-2xl hover:scale-105 transition-transform' : 'home-cta-secondary text-xl px-10 py-5 rounded-full hover:scale-105 transition-transform'}
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
