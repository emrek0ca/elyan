'use client';

import { useEffect, useRef, useState, type CSSProperties, type PropsWithChildren } from 'react';

type AnimatedBlockProps = PropsWithChildren<{
  delay?: number;
  className?: string;
}>;

/**
 * Scroll-reveal wrapper built on a CSS transition rather than a rAF tween.
 * The reveal is an enhancement, never a gate: the default state is visible,
 * the observer + a setTimeout safety (both fire in background tabs, unlike
 * requestAnimationFrame) add `is-in`, and the CSS end-state is always visible.
 */
export function AnimatedBlock({ children, delay = 0, className }: AnimatedBlockProps) {
  const ref = useRef<HTMLDivElement>(null);
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
      { rootMargin: '0px 0px -8% 0px' }
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

  return (
    <div
      ref={ref}
      className={`reveal${inView ? ' is-in' : ''}${className ? ` ${className}` : ''}`}
      style={{ '--reveal-delay': `${delay}s` } as CSSProperties}
    >
      {children}
    </div>
  );
}
