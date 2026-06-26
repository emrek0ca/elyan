'use client';

import { useRef } from 'react';
import {
  motion,
  useScroll,
  useSpring,
  useTransform,
  useMotionValue,
  useVelocity,
  useAnimationFrame
} from 'motion/react';

interface VelocityScrollProps {
  text: string;
  defaultVelocity?: number;
  className?: string;
}

const wrap = (min: number, max: number, v: number) => {
  const rangeSize = max - min;
  return ((((v - min) % rangeSize) + rangeSize) % rangeSize) + min;
};

export function VelocityScroll({ text, defaultVelocity = 2, className = '' }: VelocityScrollProps) {
  const baseX = useMotionValue(0);
  const { scrollY } = useScroll();
  const scrollVelocity = useVelocity(scrollY);
  const smoothVelocity = useSpring(scrollVelocity, {
    damping: 50,
    stiffness: 400
  });
  const velocityFactor = useTransform(smoothVelocity, [0, 1000], [0, 5], {
    clamp: false
  });

  const directionFactor = useRef<number>(1);
  useAnimationFrame((t, delta) => {
    let moveBy = directionFactor.current * defaultVelocity * (delta / 1000);

    if (velocityFactor.get() < 0) {
      directionFactor.current = -1;
    } else if (velocityFactor.get() > 0) {
      directionFactor.current = 1;
    }

    moveBy += directionFactor.current * moveBy * velocityFactor.get();
    baseX.set(baseX.get() + moveBy);
  });

  const x = useTransform(baseX, (v) => `${wrap(-20, -45, v)}%`);

  return (
    <div className={`overflow-hidden m-0 whitespace-nowrap flex flex-nowrap leading-none select-none pointer-events-none ${className}`}>
      <motion.div className="flex whitespace-nowrap flex-nowrap" style={{ x }}>
        <span className="block mr-8 md:mr-16">{text}</span>
        <span className="block mr-8 md:mr-16">{text}</span>
        <span className="block mr-8 md:mr-16">{text}</span>
        <span className="block mr-8 md:mr-16">{text}</span>
      </motion.div>
    </div>
  );
}
