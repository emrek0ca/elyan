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
import { Particles, GlowOrb } from "../components/AnimatedText";

const { fontFamily } = loadFont();

/**
 * Scene 2 — Problem Statement (5–12s, 210 frames)
 *
 * Premium effects:
 * - Horizontal scan line wipe transition
 * - Robot shrinks and moves to corner with trail effect
 * - Kinetic typography: each word pops with different timing
 * - Background grid pattern fades in
 * - Accent line draws beneath text
 */
export const Scene2Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Scan line wipe entry
  const wipeProgress = interpolate(frame, [0, 20], [0, 100], {
    extrapolateRight: "clamp",
  });

  // Background grid
  const gridOpacity = interpolate(frame, [10, 40], [0, 0.03], {
    extrapolateRight: "clamp",
  });

  // Robot slides to top-right, shrinks
  const robotX = spring({ frame, fps, from: 0, to: 380, config: { stiffness: 50, damping: 22 } });
  const robotY = spring({ frame, fps, from: 0, to: -700, config: { stiffness: 50, damping: 22 } });
  const robotScale = spring({ frame, fps, from: 1, to: 0.25, config: { stiffness: 50, damping: 22 } });
  const robotOpacity = interpolate(frame, [0, 10, 30], [1, 1, 0.6], { extrapolateRight: "clamp" });

  // Word-by-word kinetic typography
  const words1 = ["İş", "süreçleriniz"];
  const words2 = ["otomatikleşsin."];

  const renderWord = (word: string, index: number, lineOffset: number) => {
    const wordDelay = 30 + lineOffset + index * 10;
    const f = Math.max(0, frame - wordDelay);

    const y = spring({ frame: f, fps, from: 80, to: 0, config: { stiffness: 120, damping: 13 } });
    const scale = spring({ frame: f, fps, from: 0.7, to: 1, config: { stiffness: 100, damping: 12 } });
    const opacity = interpolate(f, [0, 8], [0, 1], { extrapolateRight: "clamp" });
    const blur = interpolate(f, [0, 12], [8, 0], { extrapolateRight: "clamp" });

    return (
      <span
        key={`${lineOffset}-${index}`}
        style={{
          display: "inline-block",
          transform: `translateY(${y}px) scale(${scale})`,
          opacity,
          filter: `blur(${blur}px)`,
          marginRight: 16,
        }}
      >
        {word}
      </span>
    );
  };

  // Accent underline draws in
  const lineWidth = interpolate(frame, [70, 100], [0, 400], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });
  const lineOpacity = interpolate(frame, [70, 85], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        background: "#FFFFFF",
        overflow: "hidden",
        fontFamily,
        clipPath: `inset(0 0 ${100 - wipeProgress}% 0)`,
      }}
    >
      {/* Grid pattern background */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: gridOpacity,
          backgroundImage: `
            linear-gradient(#0A0A0A 1px, transparent 1px),
            linear-gradient(90deg, #0A0A0A 1px, transparent 1px)
          `,
          backgroundSize: "60px 60px",
        }}
      />

      <Particles count={20} color="#0A0A0A" speed={0.5} />
      <GlowOrb x={540} y={960} size={600} color="rgba(0,0,0,0.02)" />

      {/* Robot moving to corner */}
      <div
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          transform: `translate(${robotX}px, ${robotY}px) scale(${robotScale})`,
          opacity: robotOpacity,
          marginLeft: -40,
          marginTop: -40,
        }}
      >
        <Img src={staticFile("elyanRobot.png")} style={{ width: 80, height: "auto" }} />
      </div>

      {/* Kinetic text */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: "0 60px",
        }}
      >
        <div
          style={{
            fontSize: 72,
            fontWeight: 900,
            color: "#0A0A0A",
            lineHeight: 1.15,
            textAlign: "center",
          }}
        >
          <div>{words1.map((w, i) => renderWord(w, i, 0))}</div>
          <div style={{ marginTop: 8 }}>{words2.map((w, i) => renderWord(w, i, 15))}</div>
        </div>

        {/* Accent line */}
        <div
          style={{
            width: lineWidth,
            height: 4,
            background: "#0A0A0A",
            borderRadius: 2,
            marginTop: 32,
            opacity: lineOpacity,
          }}
        />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
