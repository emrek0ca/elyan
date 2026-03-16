import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { AnimatedText, GlowOrb, Particles } from "../components/AnimatedText";

const { fontFamily } = loadFont();

const pills = [
  { label: "API", angle: 0 },
  { label: "Webhook", angle: 1 },
  { label: "Claude", angle: 2 },
  { label: "Slack", angle: 3 },
  { label: "GitHub", angle: 4 },
];

/**
 * Scene 5 — Integration (33–43s, 300 frames)
 *
 * Premium effects:
 * - Zoom-in transition
 * - Pills orbit in a 3D elliptical path
 * - Connection lines from center to each pill
 * - Central hub with pulse
 * - Wave pattern background
 */
export const Scene5Integration: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Zoom-in transition
  const zoomScale = spring({
    frame,
    fps,
    from: 1.3,
    to: 1,
    config: { stiffness: 50, damping: 20 },
  });
  const zoomOpacity = interpolate(frame, [0, 15], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Central hub pulse
  const hubPulse = 1 + Math.sin(frame * 0.08) * 0.08;
  const hubGlow = 0.1 + Math.sin(frame * 0.06) * 0.05;

  // Orbit parameters
  const orbitRadiusX = 260;
  const orbitRadiusY = 140;
  const orbitSpeed = 0.012;
  const centerX = 540;
  const centerY = 1050;

  // Wave background
  const wavePoints = Array.from({ length: 20 }).map((_, i) => {
    const x = (i / 19) * 1080;
    const y = 1600 + Math.sin(frame * 0.04 + i * 0.5) * 30 + Math.sin(frame * 0.02 + i * 0.3) * 20;
    return `${x},${y}`;
  });
  const wavePath = `M0,1920 L${wavePoints.join(" L")} L1080,1920 Z`;

  return (
    <AbsoluteFill
      style={{
        background: "#FFFFFF",
        overflow: "hidden",
        fontFamily,
        opacity: zoomOpacity,
        transform: `scale(${zoomScale})`,
      }}
    >
      <Particles count={20} color="#0A0A0A" speed={0.4} />
      <GlowOrb x={540} y={960} size={500} color="rgba(80,80,200,0.03)" />

      {/* Wave background */}
      <svg
        width={1080}
        height={1920}
        style={{ position: "absolute", top: 0, left: 0 }}
        viewBox="0 0 1080 1920"
      >
        <path d={wavePath} fill="#FAFAFA" opacity={0.5} />
      </svg>

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        {/* Heading area */}
        <div style={{ marginTop: 480 }}>
          <AnimatedText
            fontSize={60}
            fontWeight={900}
            color="#0A0A0A"
            delay={10}
            animation="scaleIn"
            fontFamily={fontFamily}
          >
            Entegrasyon
          </AnimatedText>

          <div style={{ marginTop: 16, display: "flex", flexDirection: "column", alignItems: "center" }}>
            <AnimatedText
              fontSize={22}
              fontWeight={400}
              color="#6E6E73"
              delay={25}
              maxWidth={450}
              lineHeight={1.6}
              animation="blurIn"
              fontFamily={fontFamily}
            >
              Mevcut araçlarınıza sorunsuz bağlanır.
            </AnimatedText>
            <AnimatedText
              fontSize={22}
              fontWeight={400}
              color="#6E6E73"
              delay={33}
              maxWidth={450}
              lineHeight={1.6}
              animation="blurIn"
              fontFamily={fontFamily}
            >
              API, webhook ve daha fazlası.
            </AnimatedText>
          </div>
        </div>
      </AbsoluteFill>

      {/* Orbiting pills with connection lines */}
      <svg
        width={1080}
        height={1920}
        style={{ position: "absolute", top: 0, left: 0 }}
        viewBox="0 0 1080 1920"
      >
        {/* Central hub */}
        <circle cx={centerX} cy={centerY} r={20 * hubPulse} fill="#0A0A0A" opacity={0.9} />
        <circle cx={centerX} cy={centerY} r={30 * hubPulse} fill="none" stroke="#0A0A0A" strokeWidth={1} opacity={hubGlow} />
        <circle cx={centerX} cy={centerY} r={45 * hubPulse} fill="none" stroke="#0A0A0A" strokeWidth={0.5} opacity={hubGlow * 0.5} />

        {pills.map((pill, i) => {
          const pillDelay = 45 + i * 10;
          const f = Math.max(0, frame - pillDelay);
          const pillOpacity = interpolate(f, [0, 20], [0, 1], { extrapolateRight: "clamp" });
          const pillScale = spring({
            frame: f, fps, from: 0, to: 1,
            config: { stiffness: 80, damping: 14 },
          });

          const angle = frame * orbitSpeed + (i * Math.PI * 2) / pills.length;
          const x = centerX + Math.cos(angle) * orbitRadiusX;
          const y = centerY + Math.sin(angle) * orbitRadiusY;

          // Z-depth for 3D effect
          const zDepth = Math.sin(angle);
          const depthScale = 0.7 + zDepth * 0.3;
          const depthOpacity = 0.4 + zDepth * 0.6;

          return (
            <g key={i} opacity={pillOpacity * depthOpacity}>
              {/* Connection line */}
              <line
                x1={centerX} y1={centerY} x2={x} y2={y}
                stroke="#D2D2D7" strokeWidth={1}
                strokeDasharray="4 3"
                opacity={0.5}
              />
              {/* Pill */}
              <g transform={`translate(${x}, ${y}) scale(${pillScale * depthScale})`}>
                <rect
                  x={-45} y={-18} width={90} height={36}
                  rx={18} fill="#FAFAFA"
                  stroke="#D2D2D7" strokeWidth={1.5}
                />
                <text
                  textAnchor="middle" dy={5}
                  fontSize={15} fontWeight={600}
                  fill="#1D1D1F" fontFamily={fontFamily}
                >
                  {pill.label}
                </text>
              </g>
            </g>
          );
        })}
      </svg>
    </AbsoluteFill>
  );
};
