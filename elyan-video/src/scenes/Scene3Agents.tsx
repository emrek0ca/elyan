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
import { AnimatedText, GlowOrb } from "../components/AnimatedText";

const { fontFamily } = loadFont();

/**
 * Scene 3 — AI Agents (12–22s, 300 frames)
 *
 * Premium effects:
 * - Circular reveal transition (clip-path circle)
 * - Robot on a floating card with 3D perspective tilt
 * - Orbiting dots around robot
 * - Text clip-reveal animation
 * - Subtle perspective parallax on scroll
 */
export const Scene3Agents: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Circular reveal transition
  const circleReveal = interpolate(frame, [0, 30], [0, 150], {
    extrapolateRight: "clamp",
  });

  // Card 3D tilt
  const tiltX = Math.sin(frame * 0.03) * 3;
  const tiltY = Math.cos(frame * 0.025) * 4;

  // Card entrance
  const cardScale = spring({
    frame: Math.max(0, frame - 15),
    fps,
    from: 0.8,
    to: 1,
    config: { stiffness: 60, damping: 16 },
  });
  const cardOpacity = interpolate(frame, [15, 35], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Robot breathing
  const breathe = 1 + Math.sin(frame * 0.06) * 0.04;

  // Orbiting dots
  const dots = [0, 1, 2, 3, 4, 5].map((i) => {
    const angle = (frame * 0.02 + (i * Math.PI * 2) / 6);
    const radius = 120 + Math.sin(frame * 0.03 + i) * 10;
    return {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius * 0.6,
      opacity: 0.2 + Math.sin(frame * 0.04 + i * 2) * 0.15,
      size: 4 + Math.sin(frame * 0.05 + i) * 2,
    };
  });

  return (
    <AbsoluteFill
      style={{
        background: "#FFFFFF",
        overflow: "hidden",
        fontFamily,
        clipPath: `circle(${circleReveal}% at 50% 50%)`,
      }}
    >
      <GlowOrb x={540} y={750} size={500} color="rgba(100,100,255,0.04)" />
      <GlowOrb x={800} y={1300} size={300} color="rgba(0,0,0,0.02)" />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 28,
        }}
      >
        {/* Floating card with robot */}
        <div
          style={{
            opacity: cardOpacity,
            transform: `scale(${cardScale}) perspective(800px) rotateX(${tiltX}deg) rotateY(${tiltY}deg)`,
            position: "relative",
            width: 300,
            height: 300,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: 20,
          }}
        >
          {/* Card background */}
          <div
            style={{
              position: "absolute",
              inset: 0,
              borderRadius: 32,
              background: "linear-gradient(135deg, #F8F8FA 0%, #EFEFEF 100%)",
              boxShadow: "0 25px 60px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.04)",
            }}
          />

          {/* Orbiting dots */}
          {dots.map((dot, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                left: "50%",
                top: "50%",
                width: dot.size,
                height: dot.size,
                borderRadius: "50%",
                background: "#0A0A0A",
                transform: `translate(${dot.x}px, ${dot.y}px)`,
                opacity: dot.opacity,
              }}
            />
          ))}

          {/* Robot */}
          <Img
            src={staticFile("elyanRobot.png")}
            style={{
              width: 160,
              height: "auto",
              transform: `scale(${breathe})`,
              position: "relative",
              zIndex: 1,
              filter: "drop-shadow(0 8px 20px rgba(0,0,0,0.1))",
            }}
          />
        </div>

        {/* Heading with clip reveal */}
        <AnimatedText
          fontSize={60}
          fontWeight={900}
          color="#0A0A0A"
          delay={40}
          animation="clipReveal"
          fontFamily={fontFamily}
        >
          Akıllı Ajanlar
        </AnimatedText>

        {/* Subtext lines staggered */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
          <AnimatedText
            fontSize={24}
            fontWeight={400}
            color="#6E6E73"
            delay={60}
            maxWidth={500}
            lineHeight={1.6}
            animation="blurIn"
            fontFamily={fontFamily}
          >
            Claude tabanlı otomasyon ajanları,
          </AnimatedText>
          <AnimatedText
            fontSize={24}
            fontWeight={400}
            color="#6E6E73"
            delay={70}
            maxWidth={500}
            lineHeight={1.6}
            animation="blurIn"
            fontFamily={fontFamily}
          >
            iş akışlarınızı sizin yerinize yürütür.
          </AnimatedText>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
