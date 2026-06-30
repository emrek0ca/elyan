'use client';

import { useRef } from 'react';
import { motion, useScroll, useTransform } from 'motion/react';

export function ScrollPath({ className = '' }: { className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start'],
  });

  const pathLength = useTransform(scrollYProgress, [0, 0.8], [0, 1]);
  const opacity = useTransform(scrollYProgress, [0, 0.1, 0.8, 1], [0, 1, 1, 0]);

  return (
    <div ref={ref} className={`absolute inset-0 pointer-events-none flex justify-center w-full overflow-hidden ${className}`}>
      <motion.svg
        viewBox="0 0 100 2000"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="w-full h-[2000px] opacity-30 dark:opacity-20"
        style={{ opacity }}
        preserveAspectRatio="xMidYMin slice"
      >
        <motion.path
          d="M50 800 V 900 C 50 1000, 10 1050, 10 1150 V 1400 C 10 1500, 90 1550, 90 1650 V 2000"
          stroke="var(--secondary)"
          strokeWidth="2"
          strokeLinecap="round"
          style={{ pathLength }}
        />
        {/* Soft glowing trail */}
        <motion.path
          d="M50 800 V 900 C 50 1000, 10 1050, 10 1150 V 1400 C 10 1500, 90 1550, 90 1650 V 2000"
          stroke="var(--secondary)"
          strokeWidth="8"
          strokeLinecap="round"
          filter="blur(8px)"
          style={{ pathLength, opacity: 0.3 }}
        />
      </motion.svg>
    </div>
  );
}
