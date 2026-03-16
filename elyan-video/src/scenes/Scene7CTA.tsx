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
import { AnimatedText, Particles, GlowOrb } from "../components/AnimatedText";

const { fontFamily } = loadFont();

/**
 * Scene 7 — CTA / Outro (52–60s, 240 frames)
 *
 * Premium effects:
 * - Everything assembles from scattered positions
 * - URL text with dramatic scale + focus effect
 * - Animated underline swoosh
 * - Robot signature with gentle bounce
 * - Ambient particles intensify then fade
 * - Final smooth fade to white
 */
export const Scene7CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const totalFrames = 240;

  // Dramatic scale-in for URL
  const urlScale = spring({
    frame: Math.max(0, frame - 5),
    fps,
    from: 2.5,
    to: 1,
    config: { stiffness: 50, damping: 14 },
  });
  const urlOpacity = interpolate(frame, [5, 25], [0, 1], {
    extrapolateRight: "clamp",
  });
  const urlBlur = interpolate(frame, [5, 25], [12, 0], {
    extrapolateRight: "clamp",
  });

  // Underline swoosh
  const swooshWidth = interpolate(frame, [30, 55], [0, 100], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });
  const swooshOpacity = interpolate(frame, [30, 40], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });

  // Robot signature entrance
  const robotDelay = 70;
  const robotBounce = spring({
    frame: Math.max(0, frame - robotDelay),
    fps,
    from: 60,
    to: 0,
    config: { stiffness: 120, damping: 10 },
  });
  const robotOpacity = interpolate(frame, [robotDelay, robotDelay + 15], [0, 1], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });
  const robotFloat = Math.sin(Math.max(0, frame - robotDelay) * 0.08) * 5;

  // Final fade out to white (last 20 frames)
  const fadeOut = interpolate(frame, [totalFrames - 20, totalFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Particle intensity ramps up then fades
  const particleOpacity = interpolate(
    frame,
    [0, 60, totalFrames - 30, totalFrames],
    [0, 1, 1, 0],
    { extrapolateRight: "clamp" }
  );

  return (
    <AbsoluteFill
      style={{
        background: "#FFFFFF",
        overflow: "hidden",
        fontFamily,
      }}
    >
      {/* Ambient effects */}
      <div style={{ opacity: particleOpacity }}>
        <Particles count={35} color="#0A0A0A" speed={0.7} />
      </div>
      <GlowOrb x={540} y={860} size={600} color="rgba(80,80,200,0.03)" />
      <GlowOrb x={300} y={1100} size={400} color="rgba(0,0,0,0.02)" pulseSpeed={0.025} />

      {/* Main content — fades out at end */}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          opacity: fadeOut,
        }}
      >
        {/* URL with dramatic scale-in */}
        <div
          style={{
            transform: `scale(${urlScale})`,
            opacity: urlOpacity,
            filter: `blur(${urlBlur}px)`,
          }}
        >
          <div
            style={{
              fontSize: 76,
              fontWeight: 900,
              color: "#0A0A0A",
              letterSpacing: 2,
              textAlign: "center",
            }}
          >
            elyan.dev
          </div>
        </div>

        {/* Swoosh underline */}
        <div
          style={{
            width: `${swooshWidth}%`,
            maxWidth: 380,
            height: 4,
            background: "linear-gradient(90deg, transparent, #0A0A0A, transparent)",
            borderRadius: 2,
            marginTop: 12,
            opacity: swooshOpacity,
          }}
        />

        {/* Tagline */}
        <div style={{ marginTop: 28 }}>
          <AnimatedText
            fontSize={24}
            fontWeight={400}
            color="#6E6E73"
            delay={40}
            animation="blurIn"
            fontFamily={fontFamily}
          >
            Geleceği şimdiden inşa edin.
          </AnimatedText>
        </div>

        {/* Robot signature */}
        <div
          style={{
            marginTop: 56,
            opacity: robotOpacity,
            transform: `translateY(${robotBounce + robotFloat}px)`,
            filter: "drop-shadow(0 8px 20px rgba(0,0,0,0.08))",
          }}
        >
          <Img
            src={staticFile("elyanRobot.png")}
            style={{ width: 80, height: "auto", objectFit: "contain" }}
          />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
