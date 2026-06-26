import { act, createElement } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AuthSurface } from '../../src/renderer/panels/AuthSurface';

let root: Root | null = null;

function renderAuthSurface(onSubmitAuth = vi.fn()) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);

  act(() => {
    root?.render(
      createElement(AuthSurface, {
        heroImageUrl: '/auth.png',
        runtimeReady: true,
        authMode: 'register',
        authEmail: 'user@example.com',
        authPassword: 'secret1234',
        authDisplayName: 'User',
        authBusy: false,
        authError: '',
        onAuthModeChange: vi.fn(),
        onAuthEmailChange: vi.fn(),
        onAuthPasswordChange: vi.fn(),
        onAuthDisplayNameChange: vi.fn(),
        onSubmitAuth,
      }),
    );
  });

  return { container, onSubmitAuth };
}

function buttonByText(text: string): HTMLButtonElement {
  const button = Array.from(document.querySelectorAll('button')).find((candidate) =>
    candidate.textContent?.includes(text),
  );
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error(`Missing button: ${text}`);
  }
  return button;
}

describe('AuthSurface', () => {
  afterEach(() => {
    act(() => {
      root?.unmount();
    });
    root = null;
    document.body.innerHTML = '';
  });

  it('requires legal acceptance before desktop registration submits', () => {
    const { onSubmitAuth } = renderAuthSurface();

    act(() => {
      buttonByText('Devam et').click();
    });

    expect(onSubmitAuth).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('Yasal onay');
    expect(buttonByText('Kabul et ve devam et').disabled).toBe(true);

    const legalLinks = Array.from(document.querySelectorAll('.auth-legal-row a')) as HTMLAnchorElement[];
    expect(legalLinks.map((link) => link.href)).toEqual([
      'https://elyan.dev/kullanim-kosullari',
      'https://elyan.dev/gizlilik',
    ]);
    expect(legalLinks.every((link) => link.target === '_blank')).toBe(true);

    const checkboxes = Array.from(document.querySelectorAll('input[type="checkbox"]')) as HTMLInputElement[];
    expect(checkboxes).toHaveLength(2);

    act(() => {
      checkboxes[0]?.click();
      checkboxes[1]?.click();
    });

    expect(buttonByText('Kabul et ve devam et').disabled).toBe(false);

    act(() => {
      buttonByText('Kabul et ve devam et').click();
    });

    expect(onSubmitAuth).toHaveBeenCalledWith({
      termsAccepted: true,
      privacyAccepted: true,
    });
  });
});
