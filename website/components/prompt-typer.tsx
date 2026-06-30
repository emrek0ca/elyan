'use client';

import { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'motion/react';

import type { SiteLocale } from '@/lib/locales';

const PROMPTS: Record<SiteLocale, { placeholder: string; items: string[] }> = {
  tr: {
    placeholder: 'Elyan’a sor…',
    items: [
      'Bu PDF’i özetle ve kaydet',
      'Masaüstünde “Proje” klasörü aç',
      'Yarın 14:00’e toplantı ekle',
      'Bu hafta için 5 fikir bul'
    ]
  },
  en: {
    placeholder: 'Ask Elyan…',
    items: [
      'Summarize this PDF and save it',
      'Create a “Project” folder on my desktop',
      'Add a meeting tomorrow at 2 PM',
      'Find me 5 ideas for this week'
    ]
  }
};

export function PromptTyper({ locale }: { locale: SiteLocale }) {
  const copy = PROMPTS[locale] ?? PROMPTS.tr;
  const prefersReducedMotion = useReducedMotion();
  const [text, setText] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (prefersReducedMotion) {
      setText(copy.items[0]);
      return;
    }

    let promptIndex = 0;
    let charIndex = 0;
    let deleting = false;

    const tick = () => {
      const full = copy.items[promptIndex];
      if (!deleting) {
        charIndex += 1;
        setText(full.slice(0, charIndex));
        if (charIndex === full.length) {
          deleting = true;
          timer.current = setTimeout(tick, 1600);
          return;
        }
        timer.current = setTimeout(tick, 52);
      } else {
        charIndex -= 1;
        setText(full.slice(0, charIndex));
        if (charIndex === 0) {
          deleting = false;
          promptIndex = (promptIndex + 1) % copy.items.length;
          timer.current = setTimeout(tick, 320);
          return;
        }
        timer.current = setTimeout(tick, 26);
      }
    };

    timer.current = setTimeout(tick, 500);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [copy, prefersReducedMotion]);

  function jumpToDemo() {
    document.getElementById('flow-title')?.scrollIntoView({
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
      block: 'center'
    });
  }

  return (
    <button type="button" className="hero-typer" onClick={jumpToDemo} aria-label={copy.placeholder}>
      <span className="hero-typer__spark" aria-hidden="true" />
      <span className="hero-typer__text">
        {text || copy.placeholder}
        {!prefersReducedMotion && <span className="hero-typer__caret" aria-hidden="true" />}
      </span>
      <span className="hero-typer__go" aria-hidden="true">→</span>
    </button>
  );
}
