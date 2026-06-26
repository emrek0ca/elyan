'use client';

import { motion } from 'motion/react';
import { useReducedMotion } from 'motion/react';

type TextRevealProps = {
  text: string;
  className?: string;
  as?: React.ElementType;
  delay?: number;
  wordDelay?: number;
};

export function TextReveal({
  text,
  className = '',
  as: Component = 'span',
  delay = 0,
  wordDelay = 0.03
}: TextRevealProps) {
  const prefersReducedMotion = useReducedMotion();

  // Split text into words, then words into characters or just keep words.
  // For a clean look, word-by-word reveal is usually best.
  const words = text.split(' ');

  if (prefersReducedMotion) {
    return <Component className={className}>{text}</Component>;
  }

  const container = {
    hidden: { opacity: 0 },
    visible: (i = 1) => ({
      opacity: 1,
      transition: { staggerChildren: wordDelay, delayChildren: delay * i },
    }),
  };

  const child = {
    visible: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { type: 'spring' as const, damping: 20, stiffness: 100 } },
    hidden: { opacity: 0, y: 20, filter: 'blur(10px)', transition: { type: 'spring' as const, damping: 20, stiffness: 100 } },
  };

  // Convert Component to motion component
  const MotionComponent = motion.create(Component as any);

  return (
    <MotionComponent
      className={className}
      variants={container}
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: '-20px' }}
      aria-label={text}
    >
      {words.map((word, index) => (
        <motion.span
          variants={child}
          style={{ display: 'inline-block', marginRight: '0.25em' }}
          key={index}
          aria-hidden="true"
        >
          {word}
        </motion.span>
      ))}
    </MotionComponent>
  );
}
