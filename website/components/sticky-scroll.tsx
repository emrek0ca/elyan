'use client';

import React, { useRef, useState } from 'react';
import { motion, useScroll, useMotionValueEvent } from 'motion/react';
import { ParallaxImage } from './parallax-image';

export const StickyScroll = ({
  content,
  contentClassName = '',
}: {
  content: {
    title: string;
    description: string;
    image?: string;
  }[];
  contentClassName?: string;
}) => {
  const [activeCard, setActiveCard] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({
    target: ref,
    offset: ['start start', 'end start'],
  });
  const cardLength = content.length;

  return (
    <div className="relative flex justify-center w-full" ref={ref}>
      <div className="flex w-full relative z-10 justify-between items-start">
        {/* Left side text content */}
        <div className="w-full md:w-1/2 relative py-[12vh] md:py-[20vh] px-1 md:px-10 z-20">
          <div className="space-y-28 md:space-y-[34vh]">
            {content.map((item, index) => (
              <motion.div
                key={item.title + index}
                initial={{ opacity: 0.2, y: 20, filter: 'blur(4px)' }}
                whileInView={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                viewport={{ margin: "-40% 0px -40% 0px" }}
                onViewportEnter={() => setActiveCard(index)}
                transition={{ duration: 0.5 }}
                className="mt-8 md:mt-20"
              >
                <h3 className="text-3xl md:text-5xl font-bold text-[var(--text)] mb-4 md:mb-6">
                  {item.title}
                </h3>
                <p className="text-base md:text-2xl text-[var(--text-muted)] max-w-lg leading-relaxed">
                  {item.description}
                </p>
              </motion.div>
            ))}
            <div className="h-10 md:h-[20vh]" />
          </div>
        </div>

        {/* Right side pinned visual */}
        <div className={`hidden md:block w-1/2 h-[70vh] sticky top-[15vh] ${contentClassName}`}>
          {content.map((item, index) => (
            <motion.div
              key={index}
              className="absolute inset-0"
              initial={{ opacity: 0 }}
              animate={{
                opacity: activeCard === index ? 1 : 0,
                scale: activeCard === index ? 1 : 1.05,
              }}
              transition={{ duration: 0.7, ease: 'easeInOut' }}
            >
              {item.image ? (
                <div className="w-full h-full flex items-center justify-center p-8">
                  <ParallaxImage src={item.image} alt={item.title} className="w-full h-full object-contain" />
                </div>
              ) : null}
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
};
