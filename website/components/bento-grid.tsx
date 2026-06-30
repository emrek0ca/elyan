'use client';

import { useRef, useState, ReactNode } from 'react';
import { motion, useMotionValue, useSpring, useTransform } from 'motion/react';
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
  const [isHovered, setIsHovered] = useState(false);
  const [opacity, setOpacity] = useState(0);

  // Spotlight position
  const mouseX = useMotionValue(0);
  const mouseY = useMotionValue(0);

  // 3D Tilt values
  const tiltX = useMotionValue(0);
  const tiltY = useMotionValue(0);

  // Spring animations for smooth return
  const springConfig = { damping: 20, stiffness: 150, mass: 0.5 };
  const smoothTiltX = useSpring(tiltX, springConfig);
  const smoothTiltY = useSpring(tiltY, springConfig);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!divRef.current) return;
    const rect = divRef.current.getBoundingClientRect();
    
    // Spotlight
    mouseX.set(e.clientX - rect.left);
    mouseY.set(e.clientY - rect.top);

    // 3D Tilt calculations
    const xPct = (e.clientX - rect.left) / rect.width - 0.5; // -0.5 to 0.5
    const yPct = (e.clientY - rect.top) / rect.height - 0.5; // -0.5 to 0.5
    
    // Adjust multiplier for more/less extreme tilt
    tiltX.set(yPct * -15); // Rotate X based on Y
    tiltY.set(xPct * 15);  // Rotate Y based on X
  };

  const handleMouseEnter = () => {
    setIsHovered(true);
    setOpacity(1);
  };

  const handleMouseLeave = () => {
    setIsHovered(false);
    setOpacity(0);
    // Reset tilt on leave
    tiltX.set(0);
    tiltY.set(0);
  };

  return (
    <AnimatedBlock delay={delay} className="perspective-1000">
      <motion.div
        ref={divRef}
        onMouseMove={handleMouseMove}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        style={{
          rotateX: smoothTiltX,
          rotateY: smoothTiltY,
          transformStyle: 'preserve-3d',
        }}
        className={`relative overflow-hidden rounded-3xl bg-[var(--surface)] border border-[var(--outline)]/50 backdrop-blur-md transition-shadow duration-300 ${
          isHovered ? 'shadow-[var(--shadow-soft)]' : ''
        } ${className}`}
      >
        {/* Spotlight Effect */}
        <motion.div
          className="absolute inset-0 z-0 pointer-events-none transition-opacity duration-300"
          style={{ opacity }}
        >
          <motion.div
            className="absolute inset-0 z-0 bg-gradient-to-r from-white to-transparent pointer-events-none blur-[100px] opacity-10"
            style={{
              x: useTransform(mouseX, (v) => v - 200),
              y: useTransform(mouseY, (v) => v - 200),
              width: '400px',
              height: '400px',
              borderRadius: '50%',
            }}
          />
        </motion.div>

        {/* Content wrapper with a parallax push */}
        <motion.div 
          className="relative z-10 flex flex-col h-full p-8 md:p-10 justify-between"
          style={{ transform: 'translateZ(30px)' }} // Parallax out from card
        >
          {header && <div className="mb-8">{header}</div>}
          <div className="mt-auto">
            <div className="font-bold text-2xl md:text-3xl text-[var(--text)] mb-3">
              {title}
            </div>
            <div className="font-medium text-lg text-[var(--text-muted)] leading-relaxed">
              {description}
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatedBlock>
  );
};
