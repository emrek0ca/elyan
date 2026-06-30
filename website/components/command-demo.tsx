'use client';

import { useEffect, useRef, useState } from 'react';
import { useReducedMotion } from 'motion/react';

import type { SiteLocale } from '@/lib/locales';

type Command = {
  id: string;
  prompt: string;
  steps: string[];
  result: string;
};

type Copy = {
  windowTitle: string;
  youLabel: string;
  doneLabel: string;
  hint: string;
  commands: Command[];
};

const COPY: Record<SiteLocale, Copy> = {
  tr: {
    windowTitle: 'elyan',
    youLabel: 'Sen',
    doneLabel: 'Tamamlandı',
    hint: 'Bir örnek seç, Elyan’ın yaptığını izle.',
    commands: [
      {
        id: 'folder',
        prompt: 'Masaüstünde “Proje” klasörü aç',
        steps: ['İsteğini anlıyorum', 'Klasör oluşturuluyor', 'Onayın alınıyor'],
        result: '“Proje” klasörü masaüstünde oluşturuldu.'
      },
      {
        id: 'pdf',
        prompt: 'Bu raporu özetle ve PDF olarak kaydet',
        steps: ['Belge okunuyor', 'Özet çıkarılıyor', 'PDF kaydediliyor'],
        result: 'ozet.pdf, İndirilenler klasörüne kaydedildi.'
      },
      {
        id: 'calendar',
        prompt: 'Yarın 14:00’e toplantı ekle',
        steps: ['Takvim açılıyor', 'Etkinlik oluşturuluyor', 'Onayın alınıyor'],
        result: 'Yarın 14:00 — Toplantı takvime eklendi.'
      }
    ]
  },
  en: {
    windowTitle: 'elyan',
    youLabel: 'You',
    doneLabel: 'Done',
    hint: 'Pick an example and watch Elyan work.',
    commands: [
      {
        id: 'folder',
        prompt: 'Create a “Project” folder on my desktop',
        steps: ['Understanding your request', 'Creating the folder', 'Asking your approval'],
        result: '“Project” folder created on your desktop.'
      },
      {
        id: 'pdf',
        prompt: 'Summarize this report and save it as a PDF',
        steps: ['Reading the document', 'Writing the summary', 'Saving the PDF'],
        result: 'summary.pdf saved to your Downloads folder.'
      },
      {
        id: 'calendar',
        prompt: 'Add a meeting tomorrow at 2 PM',
        steps: ['Opening your calendar', 'Creating the event', 'Asking your approval'],
        result: 'Tomorrow 2:00 PM — Meeting added to your calendar.'
      }
    ]
  }
};

const STEP_MS = 850;

export function CommandDemo({ locale }: { locale: SiteLocale }) {
  const copy = COPY[locale] ?? COPY.tr;
  const commands = copy.commands;
  const prefersReducedMotion = useReducedMotion();

  const [activeIndex, setActiveIndex] = useState(0);
  const [revealed, setRevealed] = useState(0);
  const [done, setDone] = useState(false);
  const [userPicked, setUserPicked] = useState(false);
  const timers = useRef<number[]>([]);

  const active = commands[activeIndex];

  function clearTimers() {
    timers.current.forEach((id) => window.clearTimeout(id));
    timers.current = [];
  }

  // Drive the trace with setTimeout (fires in background tabs) — CSS handles
  // the visual transitions, so the demo never freezes in a half-shown state.
  useEffect(() => {
    clearTimers();
    if (prefersReducedMotion) {
      setRevealed(active.steps.length);
      setDone(true);
      return;
    }
    setRevealed(0);
    setDone(false);
    active.steps.forEach((_, i) => {
      timers.current.push(window.setTimeout(() => setRevealed(i + 1), (i + 1) * STEP_MS));
    });
    timers.current.push(
      window.setTimeout(() => setDone(true), (active.steps.length + 1) * STEP_MS)
    );
    return clearTimers;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, prefersReducedMotion]);

  // Gentle auto-advance until the visitor interacts.
  useEffect(() => {
    if (prefersReducedMotion || userPicked || !done) return;
    const t = window.setTimeout(
      () => setActiveIndex((i) => (i + 1) % commands.length),
      2400
    );
    return () => window.clearTimeout(t);
  }, [done, userPicked, prefersReducedMotion, commands.length]);

  function pick(index: number) {
    setUserPicked(true);
    setActiveIndex(index);
  }

  return (
    <div className="cmd-demo">
      <div className="cmd-demo__window" role="img" aria-label={active.prompt}>
        <div className="cmd-demo__chrome" aria-hidden="true">
          <span />
          <span />
          <span />
          <strong>{copy.windowTitle}</strong>
        </div>
        <div className="cmd-demo__screen">
          <div className="cmd-demo__thread" key={active.id}>
            <div className="cmd-demo__bubble">
              <span className="cmd-demo__who">{copy.youLabel}</span>
              <p>{active.prompt}</p>
            </div>

            <ul className="cmd-demo__steps">
              {active.steps.map((step, i) => {
                const state =
                  i < revealed ? (i === revealed - 1 && !done ? 'active' : 'done') : 'idle';
                return (
                  <li key={step} className={`cmd-demo__step is-${state}`}>
                    <span className="cmd-demo__dot" aria-hidden="true" />
                    <span>{step}</span>
                  </li>
                );
              })}
            </ul>

            {done && (
              <div className="cmd-demo__result">
                <span className="cmd-demo__check" aria-hidden="true">✓</span>
                <div>
                  <span className="cmd-demo__who">{copy.doneLabel}</span>
                  <p>{active.result}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="cmd-demo__chips" role="group" aria-label={copy.hint}>
        <span className="cmd-demo__hint">{copy.hint}</span>
        <div className="cmd-demo__chip-row">
          {commands.map((command, index) => (
            <button
              key={command.id}
              type="button"
              className={`cmd-chip${index === activeIndex ? ' is-active' : ''}`}
              aria-pressed={index === activeIndex}
              onClick={() => pick(index)}
            >
              {command.prompt}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
