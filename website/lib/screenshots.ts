import type { ScreenshotItem } from '@/content/site.types';

const desktopShots: readonly ScreenshotItem[] = [
  {
    kind: 'desktop',
    src: '/screenshots/desktop/desktop-auth.png',
    alt: 'Elyan desktop sign-in surface with mascot artwork and warm neutral background.',
    caption: 'Desktop sign-in surface keeps the same calm palette and clear operator entry point.'
  },
  {
    kind: 'desktop',
    src: '/screenshots/desktop/desktop-home.png',
    alt: 'Elyan desktop signed-in landing surface with the left rail and unified composer.',
    caption: 'Signed-in desktop surface keeps navigation, workspace, and task entry in one quiet layout.'
  }
] as const;

const mobileShots: readonly ScreenshotItem[] = [
  {
    kind: 'mobile',
    src: '/screenshots/mobile/mobile-login.png',
    alt: 'Elyan mobile sign-in screen on a warm neutral background.',
    caption: 'Mobile keeps the same quiet visual system while remaining a control surface, not a local agent runtime.'
  }
] as const;

export function getDesktopScreenshots(): readonly ScreenshotItem[] {
  return desktopShots;
}

export function getMobileScreenshots(): readonly ScreenshotItem[] {
  return mobileShots;
}
