'use client';

import { motion } from 'motion/react';
import { useReducedMotion } from 'motion/react';
import type { PropsWithChildren } from 'react';

type AnimatedBlockProps = PropsWithChildren<{
  delay?: number;
  className?: string;
}>;

export function AnimatedBlock({
  children,
  delay = 0,
  className
}: AnimatedBlockProps) {
  const prefersReducedMotion = useReducedMotion();

  return (
    <motion.div
      className={className}
      initial={
        prefersReducedMotion
          ? { opacity: 1, y: 0, filter: 'blur(0px)' }
          : { opacity: 0, y: 40, filter: 'blur(12px)', scale: 0.96 }
      }
      whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)', scale: 1 }}
      viewport={{ once: true, margin: '-50px' }}
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : { duration: 0.8, ease: [0.16, 1, 0.3, 1], delay }
      }
    >
      {children}
    </motion.div>
  );
}
