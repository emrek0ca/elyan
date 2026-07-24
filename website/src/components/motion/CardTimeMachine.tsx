import React, { useState, useMemo, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';

const TIMELINE_DATA = [
  { date: 'Today', src: 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=600&q=80', title: 'Sunset Beach' },
  { date: '1d ago', src: 'https://images.unsplash.com/photo-1470071459604-3b5ec3a7fe05?auto=format&fit=crop&w=600&q=80', title: 'Misty Mountains' },
  { date: '1w ago', src: 'https://images.unsplash.com/photo-1447752875215-b2761acb3c5d?auto=format&fit=crop&w=600&q=80', title: 'Forest Trail' },
  { date: '1m ago', src: 'https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=600&q=80', title: 'Sunlight Woods' },
  { date: '1y ago', src: 'https://images.unsplash.com/photo-1501854140801-50d01698950b?auto=format&fit=crop&w=600&q=80', title: 'Green Hills' },
];

interface CardTimeMachineProps {
  className?: string;
}

export default function CardTimeMachine({
  className = ''
}: CardTimeMachineProps) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const timelineRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const handlePointerScrub = (e: React.PointerEvent) => {
    if (!timelineRef.current) return;
    const rect = timelineRef.current.getBoundingClientRect();
    const y = e.clientY - rect.top;
    const ratio = Math.max(0, Math.min(1, y / rect.height));
    const rawIndex = ratio * (TIMELINE_DATA.length - 1);
    setHoveredIndex(rawIndex);
    setActiveIndex(Math.round(rawIndex));
  };

  const [isHovered, setIsHovered] = useState(false);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  useEffect(() => {
    if (isHovered) return;
    const interval = setInterval(() => {
      setActiveIndex((prev) => (prev + 1) % TIMELINE_DATA.length);
    }, 3000);
    return () => clearInterval(interval);
  }, [isHovered]);

  const handleMouseMove = (e: React.MouseEvent) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width - 0.5;
    const y = (e.clientY - rect.top) / rect.height - 0.5;
    setMousePos({ x, y });
  };

  const timelineNodes = useMemo(() => {
    const nodes: { type: 'main' | 'sub'; index: number; date?: string }[] = [];
    TIMELINE_DATA.forEach((item, i) => {
      nodes.push({ type: 'main', index: i, date: item.date });
      if (i < TIMELINE_DATA.length - 1) {
        for (let j = 0; j < 2; j++) {
          nodes.push({ type: 'sub', index: i + (j + 1) * 0.33 });
        }
      }
    });
    return nodes;
  }, []);

  return (
    <div 
      className={`w-full h-full flex flex-row items-center justify-center gap-2 sm:gap-6 relative overflow-visible p-2 sm:p-4 ${className}`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => { setIsHovered(false); setMousePos({ x: 0, y: 0 }); }}
      onMouseMove={handleMouseMove}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        className="absolute w-0 h-0"
        version="1.1"
      >
        <defs>
          <filter id="SkiperSquiCircleFilterLayout">
            <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
            <feColorMatrix
              in="blur"
              mode="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 18 -6"
              result="goo"
            />
            <feBlend in="SourceGraphic" in2="goo" />
          </filter>
        </defs>
      </svg>
      
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(255,255,255,0.03),transparent_70%)] pointer-events-none" />

      <motion.div 
        className="relative flex-1 w-full max-w-[800px] h-full flex items-center justify-center"
        style={{ perspective: '1200px' }}
        animate={{
          rotateY: mousePos.x * 20,
          rotateX: -mousePos.y * 20,
        }}
        transition={{ type: 'spring', stiffness: 150, damping: 20 }}
      >
        {TIMELINE_DATA.map((item, i) => {
          const offset = i - activeIndex;
          const isPast = i < activeIndex;

          return (
            <motion.div
              key={i}
              className="absolute rounded-3xl flex w-[234px] h-[416px] sm:w-[270px] sm:h-[480px] origin-center flex-col overflow-hidden pointer-events-auto cursor-pointer shadow-xl"
              onClick={() => setActiveIndex(i === activeIndex ? (i + 1) % TIMELINE_DATA.length : i)}
              initial={false}
              animate={{
                z: isPast ? 200 : -offset * 50,
                x: isPast ? -400 : offset * 35,
                y: isPast ? 0 : offset * -5,
                rotateY: isPast ? -30 : offset * -4,
                rotateX: isPast ? 10 : offset * 1,
                opacity: isPast ? 0 : 1 - Math.abs(offset) * 0.15,
                scale: isPast ? 1.2 : 1,
              }}
              transition={{ 
                type: 'spring', 
                stiffness: 250, 
                damping: 25, 
                mass: 0.8 
              }}
              style={{
                zIndex: TIMELINE_DATA.length - i,
                filter: "url(#SkiperSquiCircleFilterLayout)"
              }}
            >
              <img src={item.src} alt={item.title} referrerPolicy="no-referrer" className="w-full h-full object-cover pointer-events-none" />
              <div className="absolute inset-0 bg-black/10 pointer-events-none" />
            </motion.div>
          );
        })}
      </motion.div>

      <div 
        ref={timelineRef}
        className="relative flex flex-col items-end justify-between z-50 py-4 px-4 sm:px-1 touch-none cursor-pointer h-[200px] sm:h-[240px]"
        onPointerDown={(e) => {
          setIsDragging(true);
          handlePointerScrub(e);
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          handlePointerScrub(e);
        }}
        onPointerUp={(e) => {
          setIsDragging(false);
          setHoveredIndex(null);
          e.currentTarget.releasePointerCapture(e.pointerId);
        }}
        onPointerLeave={(e) => {
          if (!isDragging) setHoveredIndex(null);
        }}
      >
        {timelineNodes.map((node, i) => {
          if (node.type === 'main') {
            const index = node.index;
            const isSelected = activeIndex === index;

            return (
              <div
                key={`main-${index}`}
                className="relative inline-flex items-center justify-end py-[1px] w-20 group pointer-events-none"
              >
                <motion.div
                  className={`h-[3px] w-[24px] rounded-full origin-right transition-colors ${
                    isSelected
                      ? 'bg-blue-600'
                      : 'bg-black/30 group-hover:bg-black/60'
                  }`}
                  animate={{
                    scaleX: hoveredIndex === null ? 1 : (isSelected ? 1.4 : (Math.abs(index - hoveredIndex) < 0.5 ? 1.25 : 1)),
                  }}
                  transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                />
              </div>
            );
          } else {
            const isHoveringNear = hoveredIndex !== null && Math.abs(node.index - hoveredIndex) <= 0.5;

            return (
              <div 
                key={`sub-${node.index}`} 
                className="py-[1px] w-20 flex justify-end pointer-events-none"
              >
                <motion.div
                  className="h-[3px] w-[24px] rounded-full bg-black/20 origin-right"
                  animate={{
                    scaleX: hoveredIndex === null ? 1 : (isHoveringNear ? 1.15 : 1),
                    opacity: hoveredIndex === null ? 0.3 : (isHoveringNear ? 0.5 : 0.3)
                  }}
                  transition={{ type: 'spring', stiffness: 400, damping: 25 }}
                />
              </div>
            );
          }
        })}
      </div>
    </div>
  );
}
