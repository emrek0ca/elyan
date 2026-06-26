import type { ElyanDesktopApi } from '../shared/desktop-api';

declare module '*.png' {
  const src: string;
  export default src;
}

declare global {
  interface Window {
    elyanDesktop?: ElyanDesktopApi;
  }
}

export {};
