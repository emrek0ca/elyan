'use client';

import { motion, useScroll, useTransform } from 'motion/react';
import Image from 'next/image';
import { useRef } from 'react';

type ParallaxImageProps = {
  src: string;
  alt: string;
  priority?: boolean;
  className?: string;
  containerClassName?: string;
};

export function ParallaxImage({ src, alt, priority, className, containerClassName }: ParallaxImageProps) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start end', 'end start']
  });

  const scale = useTransform(scrollYProgress, [0, 1], [1.0, 1.15]);

  return (
    <div ref={ref} className={`relative overflow-hidden w-full h-full ${containerClassName || ''}`}>
      <motion.div style={{ scale }} className="absolute inset-0 w-full h-full origin-center">
        <Image
          src={src}
          alt={alt}
          fill
          className={`${className?.includes('object-') ? '' : 'object-cover'} ${className || ''}`}
          priority={priority}
        />
      </motion.div>
    </div>
  );
}
