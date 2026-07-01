import type { SiteLocale } from '@/lib/locales';

export type PageKey =
  | 'home'
  | 'desktop'
  | 'mobile'
  | 'download'
  | 'privacy'
  | 'terms'
  | 'data-deletion'
  | 'support'
  | 'ai';

export type ScreenshotKind = 'desktop' | 'mobile';

export type ScreenshotItem = {
  src: string;
  alt: string;
  caption: string;
  kind: ScreenshotKind;
};

export type VisualSection = {
  eyebrow: string;
  title: string;
  body: string;
  screenshots: readonly ScreenshotItem[];
};

export type NarrativeBlock = {
  label?: string;
  title: string;
  body: string;
  pill?: string;
};

export type LegalSection = {
  title: string;
  body: readonly string[];
};

export type HeroLink = {
  href: string;
  label: string;
};

export type SitePage = {
  key: Exclude<PageKey, 'home'>;
  heroImage?: string;
  navLabel: string;
  title: string;
  description: string;
  eyebrow: string;
  intro: string;
  sections: readonly NarrativeBlock[];
  visual?: VisualSection;
  legal?: readonly LegalSection[];
  ctas?: readonly HeroLink[];
};

export type HomeContent = {
  title: string;
  description: string;
  eyebrow: string;
  intro: string;
  ctas: readonly HeroLink[];
  loopTitle: string;
  loopSteps: readonly NarrativeBlock[];
  desktopVisual?: VisualSection;
  mobileVisual?: VisualSection;
  boundaryTitle: string;
  boundaryCopy: readonly NarrativeBlock[];
  useCasesTitle: string;
  useCases: readonly NarrativeBlock[];
  plansTitle: string;
  plans: readonly NarrativeBlock[];
  finalTitle: string;
  finalCopy: string;
  finalLinks: readonly HeroLink[];
};

export type SiteContent = {
  locale: SiteLocale;
  language: string;
  direction: 'ltr';
  siteName: string;
  siteTitle: string;
  siteDescription: string;
  heroStatement: string;
  nav: readonly HeroLink[];
  footer: {
    note: string;
    legal: readonly HeroLink[];
    support: readonly HeroLink[];
  };
  messages: {
    ui: Record<string, string>;
  };
  home: HomeContent;
  pages: Record<Exclude<PageKey, 'home'>, SitePage>;
};
