"use client";

import { motion, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import { useRef } from "react";

export function ScrollSequence({ title, subtitle }: { title?: string, subtitle?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();
  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ["start start", "end end"]
  });

  // Yumuşak, fizik tabanlı scroll (daha akıcı)
  const smoothProgress = useSpring(scrollYProgress, {
    stiffness: 82,
    damping: 32,
    mass: 0.72,
    restDelta: 0.001
  });

  // Metin animasyonları (İlk %20'lik kısımda kaybolur)
  const textY = useTransform(smoothProgress, [0, 0.2], ["0%", "-100%"]);
  const textOpacity = useTransform(smoothProgress, [0, 0.15], [1, 0]);
  const textScale = useTransform(smoothProgress, [0, 0.2], [1, 0.95]);

  // Tüm scroll boyunca devam eden, boşa gitmeyen görsel animasyonları
  // Desktop Görseli (Daha hassas dönmesi için 0 -> 0.8)
  const rotateZ = useTransform(smoothProgress, [0, 0.8], ["0deg", reduceMotion ? "0deg" : "-8deg"]);
  const desktopY = useTransform(smoothProgress, [0, 0.8], ["0%", reduceMotion ? "0%" : "8%"]);
  const desktopScale = useTransform(smoothProgress, [0, 0.8], [1, reduceMotion ? 1 : 0.95]);

  // Mobil Görsel
  const rotateZMobile = useTransform(smoothProgress, [0, 0.8], ["0deg", reduceMotion ? "0deg" : "-4deg"]);
  const mobileY = useTransform(smoothProgress, [0, 0.8], ["0%", reduceMotion ? "0%" : "14%"]);
  const mobileScale = useTransform(smoothProgress, [0, 0.8], [1, reduceMotion ? 1 : 0.97]);

  return (
    <div ref={containerRef} className="scroll-sequence relative h-[130vh] w-full">
      <div className="sticky top-0 h-screen w-full flex flex-col items-center justify-center pt-24">

        <motion.div
          style={{ y: textY, opacity: textOpacity, scale: textScale }}
          className="absolute top-32 z-40 text-center flex flex-col items-center px-6 drop-shadow-md"
        >
          {subtitle && <span className="eyebrow">{subtitle}</span>}
          {title && (
            <h2 className="text-5xl md:text-7xl font-bold tracking-tight max-w-4xl" style={{ color: "var(--text)" }}>
              {title}
            </h2>
          )}
        </motion.div>

        {/* Desktop Screenshot */}
        <motion.div
          style={{
            rotateZ,
            y: desktopY,
            scale: desktopScale,
            transformOrigin: "top left"
          }}
          className="scroll-sequence__desktop absolute z-20 w-[108%] md:w-[85%] max-w-5xl rounded-2xl md:rounded-3xl overflow-hidden border border-[var(--outline-strong)] shadow-2xl mt-24 md:mt-40"
        >
          <img
            src="/screenshots/desktop/desktop-home.png"
            alt="Elyan Desktop Interface"
            className="w-full h-auto"
          />
        </motion.div>

        {/* Mobile Screenshot */}
        <motion.div
          style={{
            rotateZ: rotateZMobile,
            y: mobileY,
            scale: mobileScale,
            transformOrigin: "top left"
          }}
          className="scroll-sequence__mobile absolute z-30 right-[-2%] md:right-[15%] top-[49%] md:top-[40%] w-[34%] md:w-[25%] max-w-[190px] md:max-w-[280px] rounded-3xl md:rounded-[2.5rem] overflow-hidden border-2 md:border-4 border-[var(--outline)] shadow-2xl bg-[var(--background)]"
        >
          <img
            src="/screenshots/mobile/mobile-login.png"
            alt="Elyan Mobile Interface"
            className="w-full h-auto"
          />
        </motion.div>

      </div>
    </div>
  );
}
