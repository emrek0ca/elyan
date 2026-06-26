import { createRoot } from 'react-dom/client';
import { TolgeeProvider } from '@tolgee/react';
import { App } from './App';
import { createTolgeeInstance, getInitialLocale } from './i18n/tolgee';
import './styles.css';

const root = document.getElementById('root');

if (!root) {
  throw new Error('Renderer root element is missing.');
}

// Determine locale before first render.
// Try to read OS locale from desktopApi if available; fallback to navigator.
const api = (window as unknown as Record<string, unknown>).desktopApi as
  | { system?: { getLocale?: () => Promise<string> } }
  | undefined;

async function init() {
  let systemLocale = 'en';
  try {
    if (api?.system?.getLocale) {
      systemLocale = await api.system.getLocale();
    } else {
      systemLocale = navigator.language ?? 'en';
    }
  } catch {
    systemLocale = navigator.language ?? 'en';
  }

  const initialLocale = getInitialLocale(systemLocale);
  const tolgee = createTolgeeInstance(initialLocale);

  // Apply saved theme immediately to avoid flicker
  try {
    const savedTheme = window.localStorage.getItem('elyan-theme');
    if (savedTheme) {
      document.documentElement.setAttribute('data-theme', savedTheme);
    }
  } catch (err) {
    console.error('Failed to apply theme on init', err);
  }

  createRoot(root!).render(
    <TolgeeProvider tolgee={tolgee} fallback={null}>
      <App />
    </TolgeeProvider>,
  );
}

init();
