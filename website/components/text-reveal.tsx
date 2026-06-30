'use client';

import { useEffect, useRef, useState, type CSSProperties, type ElementType } from 'react';

type TextRevealProps = {
  text: string;
  className?: string;
  as?: ElementType;
  delay?: number;
  wordDelay?: number;
  id?: string;
};

/**
 * Word-by-word reveal driven by CSS transitions. Robust by construction: the
 * end-state is visible even if the tab is hidden or animations never run, and
 * the full text stays in the DOM for assistive tech and crawlers.
 */
export function TextReveal({
  text,
  className = '',
  as: Component = 'span',
  delay = 0,
  wordDelay = 0.03,
  id
}: TextRevealProps) {
  const ref = useRef<HTMLElement>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setInView(true);
          observer.disconnect();
        }
      },
      { rootMargin: '0px 0px -6% 0px' }
    );
    observer.observe(el);

    const safety = window.setTimeout(() => {
      setInView(true);
      observer.disconnect();
    }, 1000);

    return () => {
      observer.disconnect();
      window.clearTimeout(safety);
    };
  }, []);

  const words = text.split(' ');

  return (
    <Component
      ref={ref}
      id={id}
      className={`text-reveal${inView ? ' is-in' : ''}${className ? ` ${className}` : ''}`}
      aria-label={text}
    >
      {words.map((word, index) => (
        <span
          key={index}
          className="text-reveal__word"
          aria-hidden="true"
          style={{ '--word-delay': `${delay + index * wordDelay}s` } as CSSProperties}
        >
          {word}
        </span>
      ))}
    </Component>
  );
}
