'use client';

import { useRef, useState } from 'react';
import { motion } from 'motion/react';
import Link from 'next/link';

interface MagneticButtonProps {
  children: React.ReactNode;
  href?: string;
  className?: string;
  as?: 'button' | 'link' | 'div';
  onClick?: () => void;
}

export function MagneticButton({
  children,
  href,
  className = '',
  as = 'button',
  onClick,
}: MagneticButtonProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ x: 0, y: 0 });

  const handleMouse = (e: React.MouseEvent<HTMLDivElement>) => {
    const { clientX, clientY } = e;
    const { height, width, left, top } = ref.current!.getBoundingClientRect();
    const middleX = clientX - (left + width / 2);
    const middleY = clientY - (top + height / 2);
    setPosition({ x: middleX * 0.2, y: middleY * 0.2 });
  };

  const reset = () => {
    setPosition({ x: 0, y: 0 });
  };

  const content = (
    <motion.div
      style={{ position: 'relative' }}
      ref={ref}
      onMouseMove={handleMouse}
      onMouseLeave={reset}
      animate={{ x: position.x, y: position.y }}
      transition={{ type: 'spring', stiffness: 150, damping: 15, mass: 0.1 }}
      className="inline-block"
    >
      <motion.div
        animate={{ x: position.x * 0.3, y: position.y * 0.3 }}
        transition={{ type: 'spring', stiffness: 150, damping: 15, mass: 0.1 }}
      >
        {children}
      </motion.div>
    </motion.div>
  );

  if (as === 'link' && href) {
    return (
      <Link href={href} className={`inline-block ${className}`} onClick={onClick}>
        {content}
      </Link>
    );
  }

  if (as === 'div') {
    return (
      <div className={`inline-block ${className}`} onClick={onClick}>
        {content}
      </div>
    );
  }

  return (
    <button className={`inline-block ${className}`} onClick={onClick}>
      {content}
    </button>
  );
}
