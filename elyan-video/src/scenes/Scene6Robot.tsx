import React from "react";
import {
  AbsoluteFill,
  Img,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
  staticFile,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { AnimatedText, Particles } from "../components/AnimatedText";

const { fontFamily } = loadFont();

/**
 * Scene 6 — Robot Showcase (43–52s, 270 frames)
 *
 * Premium effects:
 * - Robot zooms in from far with dramatic spring
 * - Multiple pulsing concentric rings (radar style)
 * - Energy particles emanate outward
 * - Radial light rays behind robot
 * - Dramatic shadow and glow
 * - Text with typewriter effect
 */
export const Scene6Robot: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Robot dramatic entrance: scale from 0.1 -> 1 with overshoot
  const robotEntryScale = spring({
    frame,
    fps,
    from: 0.1,
    to: 1,
    config: { stiffness: 40, damping: 10 },
  });
  const robotOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Continuous float
  const floatY = Math.sin(frame * 0.06) * 10;
  const floatRotate = Math.sin(frame * 0.035) * 2.5;

  // Radar rings — 4 expanding rings
  const radarRings = [0, 1, 2, 3].map((i) => {
    const ringCycle = 80;
    const phase = ((frame + i * 20) % ringCycle) / ringCycle;
    return {
      scale: 0.5 + phase * 1.5,
      opacity: (1 - phase) * 0.25,
    };
  });

  // Radial light rays
  const rayCount = 12;
  const rays = Array.from({ length: rayCount }).map((_, i) => {
    const angle = (i / rayCount) * 360 + frame * 0.3;
    const length = 300 + Math.sin(frame * 0.04 + i) * 50;
    const rayOpacity = 0.03 + Math.sin(frame * 0.05 + i * 0.5) * 0.02;
    return { angle, length, opacity: rayOpacity };
  });

  // Energy particles (outward burst)
  const energyParticles = Array.from({ length: 16 }).map((_, i) => {
    const particleCycle = 90;
    const phase = ((frame + i * (particleCycle / 16)) % particleCycle) / particleCycle;
    const angle = (i / 16) * Math.PI * 2;
    const distance = phase * 350;
    return {
      x: Math.cos(angle) * distance,
      y: Math.sin(angle) * distance,
      opacity: (1 - phase) * 0.4,
      size: (1 - phase) * 5 + 1,
    };
  });

  // Background pulse
  const bgPulse = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });

  return (
    <AbsoluteFill
      style={{
        background: "#FFFFFF",
        overflow: "hidden",
        fontFamily,
      }}
    >
      <Particles count={25} color="#0A0A0A" speed={0.6} />

      {/* Background gradient pulse */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: "40%",
          width: 800,
          height: 800,
          marginLeft: -400,
          marginTop: -400,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(0,0,0,0.04), transparent 70%)",
          transform: `scale(${1 + Math.sin(frame * 0.02) * 0.1})`,
          opacity: bgPulse,
        }}
      />

      {/* Radial light rays */}
      <svg
        width={1080}
        height={1920}
        style={{ position: "absolute" }}
        viewBox="0 0 1080 1920"
      >
        {rays.map((ray, i) => (
          <line
            key={i}
            x1={540}
            y1={750}
            x2={540 + Math.cos((ray.angle * Math.PI) / 180) * ray.length}
            y2={750 + Math.sin((ray.angle * Math.PI) / 180) * ray.length}
            stroke="#0A0A0A"
            strokeWidth={2}
            opacity={ray.opacity}
          />
        ))}
      </svg>

      {/* Radar/pulse rings */}
      {radarRings.map((ring, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: "50%",
            top: "39%",
            width: 400,
            height: 400,
            marginLeft: -200,
            marginTop: -200,
            borderRadius: "50%",
            border: "1.5px solid #0A0A0A",
            transform: `scale(${ring.scale})`,
            opacity: ring.opacity,
          }}
        />
      ))}

      {/* Energy particles */}
      {energyParticles.map((p, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: 540 + p.x,
            top: 750 + p.y,
            width: p.size,
            height: p.size,
            borderRadius: "50%",
            background: "#0A0A0A",
            opacity: p.opacity * robotOpacity,
          }}
        />
      ))}

      {/* Robot hero */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: "39%",
          transform: `translate(-50%, -50%) scale(${robotEntryScale}) translateY(${floatY}px) rotate(${floatRotate}deg)`,
          opacity: robotOpacity,
          filter: "drop-shadow(0 30px 60px rgba(0,0,0,0.15))",
        }}
      >
        <Img
          src={staticFile("elyanRobot.png")}
          style={{ height: 420, width: "auto", objectFit: "contain" }}
        />
      </div>

      {/* Text */}
      <div
        style={{
          position: "absolute",
          bottom: 360,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 12,
        }}
      >
        <AnimatedText
          fontSize={68}
          fontWeight={900}
          color="#0A0A0A"
          delay={35}
          fontStyle="italic"
          animation="scaleIn"
          fontFamily={fontFamily}
        >
          Meet ELYAN.
        </AnimatedText>

        <AnimatedText
          fontSize={28}
          fontWeight={500}
          color="#6E6E73"
          delay={50}
          animation="typewriter"
          fontFamily={fontFamily}
        >
          Sizin için çalışan ajan.
        </AnimatedText>
      </div>
    </AbsoluteFill>
  );
};
