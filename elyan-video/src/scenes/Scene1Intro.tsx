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
 * Scene 1 — Intro / Logo Reveal (0–5s, 150 frames)
 *
 * Premium effects:
 * - Particle field background
 * - Concentric rings expand outward
 * - Robot scales from 0 with elastic spring + continuous float
 * - "ELYAN" letters animate individually (per-char stagger)
 * - Tagline blur-reveals after title
 * - Soft glow orbs in background
 */
export const Scene1Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Robot entrance: scale from 0 -> 1 with overshoot spring
  const robotScale = spring({
    frame,
    fps,
    from: 0,
    to: 1,
    config: { stiffness: 60, damping: 12 },
  });

  // Continuous floating
  const floatY = Math.sin(frame * 0.07) * 12;
  const floatRotate = Math.sin(frame * 0.04) * 2;

  // Robot opacity
  const robotOpacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Concentric rings
  const rings = [0, 1, 2].map((i) => {
    const ringFrame = Math.max(0, frame - 10 - i * 8);
    const ringScale = spring({
      frame: ringFrame,
      fps,
      from: 0.3,
      to: 1 + i * 0.3,
      config: { stiffness: 40, damping: 20 },
    });
    const ringOpacity = interpolate(ringFrame, [0, 15, 40], [0, 0.15, 0], {
      extrapolateRight: "clamp",
    });
    return { scale: ringScale, opacity: ringOpacity };
  });

  // Per-character animation for "ELYAN"
  const title = "ELYAN";
  const titleChars = title.split("").map((char, i) => {
    const charDelay = 30 + i * 5;
    const charFrame = Math.max(0, frame - charDelay);
    const y = spring({
      frame: charFrame,
      fps,
      from: 80,
      to: 0,
      config: { stiffness: 100, damping: 13 },
    });
    const opacity = interpolate(charFrame, [0, 10], [0, 1], {
      extrapolateRight: "clamp",
    });
    const rotate = spring({
      frame: charFrame,
      fps,
      from: -15,
      to: 0,
      config: { stiffness: 80, damping: 14 },
    });
    return { char, y, opacity, rotate };
  });

  // Tagline blur-in
  const tagFrame = Math.max(0, frame - 60);
  const tagOpacity = interpolate(tagFrame, [0, 20], [0, 1], {
    extrapolateRight: "clamp",
  });
  const tagBlur = interpolate(tagFrame, [0, 20], [20, 0], {
    extrapolateRight: "clamp",
  });
  const tagY = spring({
    frame: tagFrame,
    fps,
    from: 30,
    to: 0,
    config: { stiffness: 70, damping: 18 },
  });

  return (
    <AbsoluteFill
      style={{
        background: "#FFFFFF",
        overflow: "hidden",
        fontFamily,
      }}
    >
      {/* Ambient particles */}
      <Particles count={40} color="#0A0A0A" speed={0.8} />

      {/* Glow orbs */}
      <GlowOrb x={540} y={700} size={500} color="rgba(120,120,255,0.04)" />
      <GlowOrb x={300} y={1200} size={350} color="rgba(0,0,0,0.03)" pulseSpeed={0.02} />

      {/* Concentric expanding rings */}
      {rings.map((ring, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            left: "50%",
            top: "42%",
            width: 300,
            height: 300,
            marginLeft: -150,
            marginTop: -150,
            borderRadius: "50%",
            border: "1.5px solid #0A0A0A",
            transform: `scale(${ring.scale})`,
            opacity: ring.opacity,
          }}
        />
      ))}

      {/* Center content */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {/* Robot */}
        <div
          style={{
            transform: `scale(${robotScale}) translateY(${floatY}px) rotate(${floatRotate}deg)`,
            opacity: robotOpacity,
            marginBottom: 40,
            filter: `drop-shadow(0 20px 40px rgba(0,0,0,0.08))`,
          }}
        >
          <Img
            src={staticFile("elyanRobot.png")}
            style={{ width: 280, height: "auto", objectFit: "contain" }}
          />
        </div>

        {/* Per-character title */}
        <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
          {titleChars.map((c, i) => (
            <span
              key={i}
              style={{
                fontSize: 96,
                fontWeight: 900,
                color: "#0A0A0A",
                letterSpacing: -2,
                display: "inline-block",
                transform: `translateY(${c.y}px) rotate(${c.rotate}deg)`,
                opacity: c.opacity,
              }}
            >
              {c.char}
            </span>
          ))}
        </div>

        {/* Tagline with blur reveal */}
        <div
          style={{
            fontSize: 30,
            fontWeight: 500,
            color: "#6E6E73",
            opacity: tagOpacity,
            filter: `blur(${tagBlur}px)`,
            transform: `translateY(${tagY}px)`,
            letterSpacing: 4,
            textTransform: "uppercase",
          }}
        >
          AI & Automation Agents
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
