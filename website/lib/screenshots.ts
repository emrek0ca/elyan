import type { ScreenshotItem } from '@/content/site.types';
import type { SiteLocale } from '@/lib/locales';

type ShotCopy = { alt: string; caption: string };

const desktopCopy: Record<SiteLocale, ShotCopy[]> = {
  tr: [
    {
      alt: 'Elyan masaüstü giriş ekranı, sıcak nötr arka plan.',
      caption: 'Bilgisayarında giriş — telefonunla aynı hesap.'
    },
    {
      alt: 'Elyan masaüstü ana ekranı; yan menü ve birleşik görev alanı.',
      caption: 'İş burada yapılır: sohbet, görevler ve sonuçlar tek ekranda.'
    }
  ],
  en: [
    {
      alt: 'Elyan desktop sign-in screen on a warm neutral background.',
      caption: 'Sign in on your computer — the same account as your phone.'
    },
    {
      alt: 'Elyan desktop home screen with the side rail and unified task area.',
      caption: 'The work happens here: chat, tasks and results in one place.'
    }
  ]
};

const mobileCopy: Record<SiteLocale, ShotCopy[]> = {
  tr: [
    {
      alt: 'Elyan mobil giriş ekranı, sıcak nötr arka plan.',
      caption: 'Telefonda giriş — gerisini bilgisayarın halleder.'
    }
  ],
  en: [
    {
      alt: 'Elyan mobile sign-in screen on a warm neutral background.',
      caption: 'Sign in on your phone — your computer does the rest.'
    }
  ]
};

const desktopSrc = [
  '/screenshots/desktop/desktop-auth.png',
  '/screenshots/desktop/desktop-home.png'
] as const;

const mobileSrc = ['/screenshots/mobile/mobile-login.png'] as const;

export function getDesktopScreenshots(locale: SiteLocale): readonly ScreenshotItem[] {
  return desktopSrc.map((src, index) => ({
    kind: 'desktop' as const,
    src,
    alt: desktopCopy[locale][index].alt,
    caption: desktopCopy[locale][index].caption
  }));
}

export function getMobileScreenshots(locale: SiteLocale): readonly ScreenshotItem[] {
  return mobileSrc.map((src, index) => ({
    kind: 'mobile' as const,
    src,
    alt: mobileCopy[locale][index].alt,
    caption: mobileCopy[locale][index].caption
  }));
}
