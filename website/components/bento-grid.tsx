'use client';

import { useRef, useState, ReactNode } from 'react';
import { AnimatedBlock } from './animated-block';

export const BentoGrid = ({
  className = '',
  children,
}: {
  className?: string;
  children?: ReactNode;
}) => {
  return (
    <div
      className={`grid grid-cols-1 md:grid-cols-3 gap-6 max-w-7xl mx-auto ${className}`}
    >
      {children}
    </div>
  );
};

export const BentoCard = ({
  className = '',
  title,
  description,
  header,
  delay = 0,
}: {
  className?: string;
  title: string | ReactNode;
  description: string | ReactNode;
  header?: ReactNode;
  delay?: number;
}) => {
  const divRef = useRef<HTMLDivElement>(null);
  const [isFocused, setIsFocused] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [opacity, setOpacity] = useState(0);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!divRef.current || isFocused) return;

    const div = divRef.current;
    const rect = div.getBoundingClientRect();

    setPosition({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  const handleFocus = () => {
    setIsFocused(true);
    setOpacity(1);
  };

  const handleBlur = () => {
    setIsFocused(false);
    setOpacity(0);
  };

  const handleMouseEnter = () => {
    setOpacity(1);
  };

  const handleMouseLeave = () => {
    setOpacity(0);
  };

  return (
    <AnimatedBlock
      delay={delay}
      className={`relative overflow-hidden rounded-3xl bg-[var(--surface)] border border-[var(--outline)]/50 backdrop-blur-md group transition-transform duration-300 hover:-translate-y-1 ${className}`}
    >
      <div
        ref={divRef}
        onMouseMove={handleMouseMove}
        onFocus={handleFocus}
        onBlur={handleBlur}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        className="absolute inset-0 z-0 pointer-events-none transition-opacity duration-300"
        style={{ opacity }}
      >
        <div
          className="absolute inset-0 z-0 bg-gradient-to-r from-white to-transparent pointer-events-none blur-[100px] opacity-10"
          style={{
            transform: `translate(${position.x - 200}px, ${position.y - 200}px)`,
            width: '400px',
            height: '400px',
            borderRadius: '50%',
          }}
        />
      </div>

      <div className="relative z-10 flex flex-col h-full p-8 md:p-10 justify-between">
        {header && <div className="mb-8">{header}</div>}
        <div className="mt-auto">
          <div className="font-bold text-2xl md:text-3xl text-[var(--text)] mb-3">
            {title}
          </div>
          <div className="font-medium text-lg text-[var(--text-muted)] leading-relaxed">
            {description}
          </div>
        </div>
      </div>
    </AnimatedBlock>
  );
};
