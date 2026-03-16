import React from "react";
import { useCurrentFrame, useVideoConfig, spring, interpolate } from "remotion";

interface AnimatedTextProps {
  children: string;
  fontSize?: number;
  fontWeight?: number | string;
  color?: string;
  /** Frame delay before animation starts */
  delay?: number;
  letterSpacing?: number;
  maxWidth?: number;
  lineHeight?: number;
  fontStyle?: "normal" | "italic";
  fontFamily?: string;
  /** Animation type */
  animation?: "slideUp" | "clipReveal" | "scaleIn" | "typewriter" | "blurIn";
}

/**
 * Premium text reveal component with multiple animation modes.
 */
export const AnimatedText: React.FC<AnimatedTextProps> = ({
  children,
  fontSize = 48,
  fontWeight = 700,
  color = "#0A0A0A",
  delay = 0,
  letterSpacing = 0,
  maxWidth,
  lineHeight = 1.15,
  fontStyle = "normal",
  fontFamily = "Inter, system-ui, -apple-system, sans-serif",
  animation = "slideUp",
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const f = Math.max(0, frame - delay);

  const baseStyle: React.CSSProperties = {
    fontSize,
    fontWeight,
    color,
    letterSpacing,
    lineHeight,
    fontStyle,
    fontFamily,
    maxWidth: maxWidth ? `${maxWidth}px` : undefined,
    textAlign: "center" as const,
    willChange: "transform, opacity, filter",
  };

  if (animation === "slideUp") {
    const opacity = interpolate(f, [0, 18], [0, 1], { extrapolateRight: "clamp" });
    const y = spring({ frame: f, fps, from: 50, to: 0, config: { stiffness: 80, damping: 16 } });
    return <div style={{ ...baseStyle, opacity, transform: `translateY(${y}px)` }}>{children}</div>;
  }

  if (animation === "clipReveal") {
    const reveal = interpolate(f, [0, 25], [0, 100], { extrapolateRight: "clamp" });
    return (
      <div style={{ ...baseStyle, clipPath: `inset(0 ${100 - reveal}% 0 0)` }}>
        {children}
      </div>
    );
  }

  if (animation === "scaleIn") {
    const s = spring({ frame: f, fps, from: 0.3, to: 1, config: { stiffness: 100, damping: 14 } });
    const opacity = interpolate(f, [0, 12], [0, 1], { extrapolateRight: "clamp" });
    return (
      <div style={{ ...baseStyle, opacity, transform: `scale(${s})` }}>{children}</div>
    );
  }

  if (animation === "blurIn") {
    const opacity = interpolate(f, [0, 20], [0, 1], { extrapolateRight: "clamp" });
    const blur = interpolate(f, [0, 20], [16, 0], { extrapolateRight: "clamp" });
    const y = spring({ frame: f, fps, from: 20, to: 0, config: { stiffness: 70, damping: 18 } });
    return (
      <div style={{ ...baseStyle, opacity, filter: `blur(${blur}px)`, transform: `translateY(${y}px)` }}>
        {children}
      </div>
    );
  }

  if (animation === "typewriter") {
    const charCount = Math.floor(interpolate(f, [0, children.length * 2], [0, children.length], { extrapolateRight: "clamp" }));
    return <div style={{ ...baseStyle }}>{children.slice(0, charCount)}<span style={{ opacity: f % 16 < 8 ? 1 : 0 }}>|</span></div>;
  }

  // Default fallback
  const opacity = interpolate(f, [0, 18], [0, 1], { extrapolateRight: "clamp" });
  return <div style={{ ...baseStyle, opacity }}>{children}</div>;
};

/**
 * Floating particles background effect
 */
export const Particles: React.FC<{
  count?: number;
  color?: string;
  speed?: number;
}> = ({ count = 30, color = "#0A0A0A", speed = 1 }) => {
  const frame = useCurrentFrame();

  // Deterministic pseudo-random from seed
  const particles = React.useMemo(() => {
    const arr = [];
    for (let i = 0; i < count; i++) {
      const seed = i * 7919;
      arr.push({
        x: (seed * 13) % 1080,
        y: (seed * 17) % 1920,
        size: 2 + (seed % 4),
        speedX: ((seed % 100) - 50) * 0.01 * speed,
        speedY: ((seed % 80) - 40) * 0.01 * speed,
        phase: (seed % 360),
      });
    }
    return arr;
  }, [count, speed]);

  return (
    <>
      {particles.map((p, i) => {
        const x = p.x + Math.sin((frame * 0.02 + p.phase) * p.speedX) * 80;
        const y = p.y + Math.cos((frame * 0.015 + p.phase) * p.speedY) * 60;
        const opacity = 0.06 + Math.sin(frame * 0.03 + p.phase) * 0.04;
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: p.size,
              height: p.size,
              borderRadius: "50%",
              background: color,
              opacity,
            }}
          />
        );
      })}
    </>
  );
};

/**
 * Animated gradient orb — soft glowing circle
 */
export const GlowOrb: React.FC<{
  x: number;
  y: number;
  size?: number;
  color?: string;
  pulseSpeed?: number;
}> = ({ x, y, size = 400, color = "rgba(0,0,0,0.03)", pulseSpeed = 0.03 }) => {
  const frame = useCurrentFrame();
  const scale = 1 + Math.sin(frame * pulseSpeed) * 0.1;
  const opacity = 0.8 + Math.sin(frame * pulseSpeed * 1.3) * 0.2;

  return (
    <div
      style={{
        position: "absolute",
        left: x - size / 2,
        top: y - size / 2,
        width: size,
        height: size,
        borderRadius: "50%",
        background: `radial-gradient(circle, ${color}, transparent 70%)`,
        transform: `scale(${scale})`,
        opacity,
      }}
    />
  );
};
