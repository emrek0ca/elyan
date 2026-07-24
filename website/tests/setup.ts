import { afterEach, beforeEach } from 'vitest';

beforeEach(() => {
  process.env.NODE_ENV = 'test';
  process.env.ELYAN_API_BASE_URL = 'https://api.elyan.dev';
  process.env.ELYAN_WEB_ORIGIN = 'http://localhost:4321';
  process.env.ELYAN_WEB_SESSION_SECRET = 'test-session-secret-with-at-least-32-characters';
});

afterEach(() => {
  document.body.replaceChildren();
  document.cookie.split(';').forEach((entry) => {
    document.cookie = `${entry.split('=')[0]?.trim()}=; Max-Age=0; Path=/`;
  });
  sessionStorage.clear();
});
