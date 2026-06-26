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
          : { opacity: 0, y: 20, filter: 'blur(8px)' }
      }
      whileInView={
        prefersReducedMotion
          ? { opacity: 1, y: 0, filter: 'blur(0px)' }
          : { opacity: 1, y: 0, filter: 'blur(0px)' }
      }
      viewport={{ once: true, margin: '-50px' }}
      transition={
        prefersReducedMotion
          ? { duration: 0 }
          : { duration: 0.6, ease: 'easeOut', delay }
      }
    >
      {children}
    </motion.div>
  );
}
