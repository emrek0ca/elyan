import React from "react";
import { useCurrentFrame, useVideoConfig, spring, interpolate, AbsoluteFill } from "remotion";

export const BPM = 128;
export const FPS = 30;

/* ─────────────────────────────────────────────
   VFXStack — Ultimate High-End Visual Effects
   ───────────────────────────────────────────── */
export const VFXStack: React.FC<{ children: React.ReactNode; intensity?: number }> = ({ children, intensity = 1 }) => {
  const frame = useCurrentFrame();
  
  return (
    <AbsoluteFill>
      {/* Premium Apple Surface - Soft Radial Gradient */}
      <AbsoluteFill style={{
        background: "radial-gradient(circle at 50% 30%, #FFFFFF 0%, #F5F5F7 100%)",
      }} />

      {/* Cinematic High-Fidelity Grain */}
      <AbsoluteFill style={{
        opacity: 0.04 * intensity,
        pointerEvents: "none",
        backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
        mixBlendMode: "multiply",
      }} />

      {/* Subtle Depth Shadow Vignette */}
      <AbsoluteFill style={{
        background: "radial-gradient(circle, transparent 20%, rgba(0,0,0,0.03) 100%)",
        pointerEvents: "none",
      }} />

      {/* Content Layer */}
      <div style={{ height: "100%", width: "100%", position: "relative" }}>
        {children}
      </div>

      {/* Dynamic Specular "Glass" Sweep */}
      <AbsoluteFill style={{
        background: `linear-gradient(135deg, transparent 40%, rgba(255,255,255,0.4) 50%, transparent 60%)`,
        backgroundSize: "200% 200%",
        backgroundPosition: `${(frame % 120) / 120 * 200}% 0%`,
        pointerEvents: "none",
        mixBlendMode: "overlay",
        opacity: 0.3,
      }} />
    </AbsoluteFill>
  );
};

/* ─────────────────────────────────────────────
   Stage3D — Perspective Environment
   ───────────────────────────────────────────── */
export const Stage3D: React.FC<{ children: React.ReactNode; perspective?: number; rotateX?: number; rotateY?: number }> = ({ 
  children, perspective = 1200, rotateX = 0, rotateY = 0 
}) => {
  return (
    <div style={{
      perspective,
      perspectiveOrigin: "50% 50%",
      width: "100%", height: "100%",
      transformStyle: "preserve-3d",
      display: "flex", alignItems: "center", justifyContent: "center",
      transform: `rotateX(${rotateX}deg) rotateY(${rotateY}deg)`,
    }}>
      {children}
    </div>
  );
};

/* ─────────────────────────────────────────────
   ReflectiveGlass — Ultra High-End Liquid Physics
   ───────────────────────────────────────────── */
export const ReflectiveGlass: React.FC<{ 
  children: React.ReactNode; 
  style?: React.CSSProperties; 
  intensity?: number;
  depth?: number;
}> = ({ children, style, intensity = 1, depth = 0 }) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const scale = width / 1080;
  
  // Simulated specular light sweep across surface
  const sweepPos = (frame % 180) / 180 * 400 - 150;

  return (
    <div style={{
      background: "rgba(255, 255, 255, 0.4)",
      backdropFilter: `blur(${25 * scale}px) saturate(180%) brightness(1.1)`,
      WebkitBackdropFilter: `blur(${25 * scale}px) saturate(180%) brightness(1.1)`,
      border: `${1.5 * scale}px solid rgba(255, 255, 255, 0.8)`,
      boxShadow: `
        0 ${10 * scale}px ${30 * scale}px rgba(0,0,0,0.05),
        0 ${30 * scale}px ${80 * scale}px rgba(0,0,0,0.08),
        inset 0 0 0 ${1.5 * scale}px rgba(255,255,255,0.5)
      `,
      borderRadius: style?.borderRadius ? Number(style.borderRadius) * scale : 45 * scale,
      overflow: "hidden",
      position: "relative",
      transform: `translateZ(${depth * scale}px)`,
      transformStyle: "preserve-3d",
      ...style,
    }}>
      {/* Liquid Refraction Layer - Simulates light bending at edges */}
      <div style={{
        position: "absolute", inset: 0,
        background: `linear-gradient(135deg, rgba(255,255,255,0.4) 0%, transparent 40%, rgba(255,255,255,0.2) 100%)`,
        opacity: 0.8, pointerEvents: "none",
      }} />

      {/* Dynamic Caustic Highlight Sweep */}
      <div style={{
        position: "absolute", top: 0, left: `${sweepPos}%`, width: "100%", height: "100%",
        background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.6), transparent)",
        transform: "skewX(-25deg)",
        opacity: 0.4, pointerEvents: "none", filter: "blur(20px)",
      }} />

      {/* Internal Glass Thickness - 3D Look */}
      <div style={{
        position: "absolute", inset: 2, borderRadius: "inherit",
        border: "1px solid rgba(255,255,255,0.2)", pointerEvents: "none",
      }} />

      <div style={{ position: "relative", zIndex: 10 }}>
        {children}
      </div>
    </div>
  );
};

export const GlassCard: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <ReflectiveGlass style={{ padding: "40px 60px", ...style }}>
    {children}
  </ReflectiveGlass>
);

export const VFX: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { width } = useVideoConfig();
  const scale = width / 1080;
  return (
    <AbsoluteFill>
      {children}
      {/* Refined Minimal Corner Markers */}
      <AbsoluteFill style={{ pointerEvents: "none" }}>
        <div style={{ position: "absolute", top: 80 * scale, left: 80 * scale, width: 30 * scale, height: 1.5 * scale, background: "rgba(0,0,0,0.15)" }} />
        <div style={{ position: "absolute", top: 80 * scale, left: 80 * scale, width: 1.5 * scale, height: 30 * scale, background: "rgba(0,0,0,0.15)" }} />
        <div style={{ position: "absolute", top: 80 * scale, right: 80 * scale, width: 30 * scale, height: 1.5 * scale, background: "rgba(0,0,0,0.15)" }} />
        <div style={{ position: "absolute", top: 80 * scale, right: 80 * scale, width: 1.5 * scale, height: 30 * scale, background: "rgba(0,0,0,0.15)" }} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/* ─────────────────────────────────────────────
   ImpactText — Extreme Kinetic Reveal
   ───────────────────────────────────────────── */
export const ImpactText: React.FC<{
  children: string;
  fontSize?: number;
  delay?: number;
  letterSpacing?: number;
  color?: string;
}> = ({ children, fontSize = 90, delay = 0, letterSpacing = 4, color = "#0A0A0A" }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig(); // Scale support
  const scaleFactor = width / 1080;
  const f = Math.max(0, frame - delay);

  const bounce = spring({
    frame: f,
    fps,
    config: { stiffness: 220, damping: 10, mass: 0.6 },
  });

  const blur = interpolate(f, [0, 10], [40 * scaleFactor, 0], { extrapolateRight: "clamp" });
  const opacity = interpolate(f, [0, 6], [0, 1]);
  const scale = interpolate(bounce, [0, 1], [3, 1]);

  return (
    <div style={{
      fontSize: fontSize * scaleFactor, fontWeight: 900, color,
      letterSpacing: (letterSpacing + (1 - bounce) * 50) * scaleFactor,
      transform: `scale(${scale})`,
      opacity,
      filter: `blur(${blur}px)`,
      textAlign: "center",
      textTransform: "uppercase",
      willChange: "transform, opacity, filter",
    }}>
      {children}
    </div>
  );
};

/* ─────────────────────────────────────────────
   AnimatedText — Cinematic Variant
   ───────────────────────────────────────────── */
export const AnimatedText: React.FC<{
  children: string;
  fontSize?: number;
  fontWeight?: number | string;
  color?: string;
  delay?: number;
  animation?: "slideUp" | "blurIn" | "perChar";
  textAlign?: "center" | "left" | "right";
  textTransform?: "none" | "uppercase";
  letterSpacing?: number;
}> = ({ children, fontSize = 48, fontWeight = 700, color = "#0A0A0A", delay = 0, animation = "slideUp", textAlign = "center", textTransform = "none", letterSpacing }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const scaleFactor = width / 1080;
  const f = Math.max(0, frame - delay);

  if (animation === "perChar") {
    return (
      <div style={{ display: "flex", justifyContent: textAlign === "center" ? "center" : "flex-start", flexWrap: "wrap", width: "100%" }}>
        {children.split("").map((char, i) => {
          const cf = Math.max(0, f - i * 1.5);
          const y = spring({ frame: cf, fps, from: 40 * scaleFactor, to: 0, config: { stiffness: 180, damping: 12 } });
          return (
            <span key={i} style={{ 
              fontSize: fontSize * scaleFactor, fontWeight, color, textTransform, 
              letterSpacing: letterSpacing ? letterSpacing * scaleFactor : undefined, 
              display: "inline-block", transform: `translateY(${y}px)`, 
              opacity: interpolate(cf, [0, 6], [0, 1]), 
              minWidth: char === " " ? "0.3em" : undefined 
            }}>
              {char === " " ? "\u00A0" : char}
            </span>
          );
        })}
      </div>
    );
  }

  const y = spring({ frame: f, fps, from: 50 * scaleFactor, to: 0, config: { stiffness: 100, damping: 18 } });
  
  return (
    <div style={{
      fontSize: fontSize * scaleFactor, fontWeight, color, textAlign, textTransform, 
      letterSpacing: letterSpacing ? letterSpacing * scaleFactor : undefined,
      opacity: interpolate(f, [0, 15], [0, 1]),
      transform: `translateY(${y}px)`,
      filter: animation === "blurIn" ? `blur(${interpolate(f, [0, 15], [15 * scaleFactor, 0])}px)` : undefined,
    }}>
      {children}
    </div>
  );
};

/* ─────────────────────────────────────────────
   Cinematic Components (Enhanced 3D)
   ───────────────────────────────────────────── */
export const CinematicGrid: React.FC<{ opacity?: number; color?: string; z?: number }> = ({ opacity = 0.05, color = "#000", z = -100 }) => {
  const { width } = useVideoConfig();
  const scale = width / 1080;
  return (
    <AbsoluteFill style={{
      opacity,
      backgroundImage: `linear-gradient(${color} ${1 * scale}px, transparent ${1 * scale}px), linear-gradient(90deg, ${color} ${1 * scale}px, transparent ${1 * scale}px)`,
      backgroundSize: `${100 * scale}px ${100 * scale}px`,
      transform: `translateZ(${z * scale}px)`,
    }} />
  );
};

export const Particles: React.FC<{ count?: number; colors?: string[]; speed?: number }> = ({ count = 60, colors = ["#0A0A0A"], speed = 1 }) => {
  const frame = useCurrentFrame();
  const { width, height: viewHeight } = useVideoConfig();
  const scale = width / 1080;

  return (
    <AbsoluteFill style={{ transformStyle: "preserve-3d" }}>
      {Array.from({ length: count }).map((_, i) => {
        const seed = i * 144.4;
        const x = ((seed % 1080) * scale) + Math.sin(frame * 0.02 * speed + seed) * (150 * scale);
        const y = (((seed * 1.5) % 1920) * scale) + Math.cos(frame * 0.015 * speed + seed) * (200 * scale);
        const z = ((seed % 1000) - 500 + Math.sin(frame * 0.03 * speed) * 300) * scale;
        return (
          <div key={i} style={{
            position: "absolute", left: x, top: y,
            width: (3 + (seed % 5)) * scale, height: (3 + (seed % 5)) * scale,
            borderRadius: "50%", background: colors[i % colors.length],
            opacity: 0.1 + Math.sin(frame * 0.05 + seed) * 0.1,
            transform: `translateZ(${z}px)`,
          }} />
        );
      })}
    </AbsoluteFill>
  );
};

/* ─────────────────────────────────────────────
   LiquidBlob — Organic Refractive Fluid
   ───────────────────────────────────────────── */
export const LiquidBlob: React.FC<{ x: number; y: number; size?: number; color?: string; opacity?: number; z?: number }> = ({ 
  x, y, size = 400, color = "#0071E3", opacity = 0.1, z = -150 
}) => {
  const frame = useCurrentFrame();
  const { width } = useVideoConfig();
  const scale = width / 1080;
  const float = Math.sin(frame * 0.03) * (50 * scale);
  
  return (
    <div style={{
      position: "absolute", 
      left: (x * scale) - (size * scale) / 2, 
      top: (y * scale) - (size * scale) / 2 + float,
      width: size * scale, height: size * scale,
      borderRadius: "45% 55% 58% 42% / 44% 43% 57% 56%", // Organic blobbiness
      background: `radial-gradient(circle at 30% 30%, rgba(255,255,255,0.4), ${color} 70%)`,
      filter: `blur(${60 * scale}px)`,
      opacity,
      transform: `translateZ(${z * scale}px) scale(${1 + Math.sin(frame * 0.02) * 0.1})`,
      pointerEvents: "none",
    }} />
  );
};

export const ColorOrb: React.FC<{ x: number; y: number; size?: number; colors?: string[]; opacity?: number; z?: number }> = ({ x, y, size = 1000, colors = ["#6A11CB", "#2575FC"], opacity = 0.15, z = -200 }) => {
  const frame = useCurrentFrame();
  const scale = 1 + Math.sin(frame * 0.04) * 0.15;
  return (
    <div style={{
      position: "absolute", left: x - size / 2, top: y - size / 2,
      width: size, height: size, borderRadius: "50%",
      background: `radial-gradient(circle, ${colors[0]}, ${colors[1] || "transparent"} 70%)`,
      filter: "blur(100px)", opacity,
      transform: `translateZ(${z}px) scale(${scale})`,
    }} />
  );
};

/* ─────────────────────────────────────────────
   Cinematic Elite Optics
   ───────────────────────────────────────────── */

/** Anamorphic Lens Flare - Iconic Cinematic Streak */
export const AnamorphicFlare: React.FC<{ 
  color?: string; 
  opacity?: number; 
  y?: number;
  width?: number;
}> = ({ color = "#80BFFF", opacity = 0.4, y = 50, width = 1200 }) => {
  const { width: viewWidth } = useVideoConfig(); // useVideoConfig inside component
  const scale = viewWidth / 1080;
  return (
    <div style={{
      position: "absolute",
      left: "50%",
      top: `${y}%`,
      transform: "translate(-50%, -50%)",
      width: width * scale,
      height: 2.5 * scale,
      background: `linear-gradient(90deg, 
        transparent 0%, 
        ${color} 20%, 
        #FFF 50%, 
        ${color} 80%, 
        transparent 100%
      )`,
      boxShadow: `0 0 ${40 * scale}px ${10 * scale}px ${color}`,
      opacity,
      pointerEvents: "none",
      filter: `blur(${4 * scale}px)`,
      zIndex: 1000,
    }} />
  );
};

/** High-End Film Grain Simulation */
export const FilmGrain: React.FC<{ opacity?: number }> = ({ opacity = 0.04 }) => (
  <div style={{
    position: "absolute",
    inset: 0,
    opacity,
    pointerEvents: "none",
    zIndex: 9999,
    background: `url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E")`,
    mixBlendMode: "multiply",
  }} />
);

/** Master Cinematic Layer - Post Processing Stack */
export const CinematicPostProcessing: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <AbsoluteFill style={{ overflow: "hidden" }}>
    <div style={{
      width: "100%", height: "100%",
      position: "relative",
      filter: "contrast(1.02) saturate(1.05)", // Commercial Grade Color Grading
    }}>
      {children}
      
      {/* Chromatic Aberration Simulation */}
      <div style={{
        position: "absolute", inset: 0,
        pointerEvents: "none",
        border: "1px solid transparent",
        boxShadow: "inset 0 0 100px rgba(0,0,0,0.05)",
        zIndex: 9000,
      }} />
      
      <FilmGrain />
      
      {/* Subtle Optical Vignette */}
      <div style={{
        position: "absolute", inset: 0,
        background: "radial-gradient(circle at center, transparent 40%, rgba(0,0,0,0.02) 100%)",
        pointerEvents: "none",
        zIndex: 9001,
      }} />
    </div>
  </AbsoluteFill>
);
