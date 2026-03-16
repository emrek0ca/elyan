import React from "react";
import {
  AbsoluteFill,
  useCurrentFrame,
  useVideoConfig,
  spring,
  interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { AnimatedText, Particles, GlowOrb } from "../components/AnimatedText";

const { fontFamily } = loadFont();

/**
 * Scene 4 — Automation (22–33s, 330 frames)
 *
 * Premium effects:
 * - Vertical slide-in transition
 * - Animated workflow: 4 nodes connected with animated flowing paths
 * - Nodes pulse with sequential activation (cascade glow)
 * - Flowing particles along the connection lines
 * - Background noise texture
 */
export const Scene4Automation: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Entry: vertical blinds effect
  const blindsCount = 8;
  const blindsReveal = interpolate(frame, [0, 25], [0, 1], {
    extrapolateRight: "clamp",
  });

  // Node definitions (vertical layout for story format)
  const nodes = [
    { label: "Veri", y: 580, delay: 40, icon: "◈" },
    { label: "İşlem", y: 780, delay: 55, icon: "⟐" },
    { label: "AI", y: 980, delay: 70, icon: "◎" },
    { label: "Sonuç", y: 1180, delay: 85, icon: "✦" },
  ];

  // Connection line drawing
  const lineDrawProgress = (fromDelay: number) => {
    const f = Math.max(0, frame - fromDelay - 10);
    return interpolate(f, [0, 25], [0, 1], { extrapolateRight: "clamp" });
  };

  // Cascade activation (glow that travels through nodes)
  const cascadePhase = interpolate(frame, [90, 200], [0, 3], {
    extrapolateRight: "clamp",
    extrapolateLeft: "clamp",
  });

  return (
    <AbsoluteFill
      style={{
        background: "#FFFFFF",
        overflow: "hidden",
        fontFamily,
      }}
    >
      {/* Vertical blinds reveal */}
      {Array.from({ length: blindsCount }).map((_, i) => {
        const blindDelay = i * 2;
        const blindH = interpolate(frame, [blindDelay, blindDelay + 18], [0, 100], {
          extrapolateRight: "clamp",
          extrapolateLeft: "clamp",
        });
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${(i / blindsCount) * 100}%`,
              top: 0,
              width: `${100 / blindsCount + 1}%`,
              height: `${blindH}%`,
              background: "#FFFFFF",
              zIndex: 0,
            }}
          />
        );
      })}

      <Particles count={15} color="#0A0A0A" speed={0.3} />
      <GlowOrb x={540} y={880} size={700} color="rgba(0,0,0,0.015)" />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          opacity: blindsReveal,
        }}
      >
        {/* Heading */}
        <div style={{ marginTop: 300 }}>
          <AnimatedText
            fontSize={58}
            fontWeight={900}
            color="#0A0A0A"
            delay={12}
            animation="scaleIn"
            fontFamily={fontFamily}
          >
            Tam Otomasyon
          </AnimatedText>
        </div>

        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", alignItems: "center" }}>
          <AnimatedText
            fontSize={22}
            fontWeight={400}
            color="#6E6E73"
            delay={25}
            maxWidth={450}
            lineHeight={1.6}
            animation="slideUp"
            fontFamily={fontFamily}
          >
            Tekrarlayan görevleri ortadan kaldırın.
          </AnimatedText>
          <AnimatedText
            fontSize={22}
            fontWeight={400}
            color="#6E6E73"
            delay={33}
            maxWidth={450}
            lineHeight={1.6}
            animation="slideUp"
            fontFamily={fontFamily}
          >
            Ekibiniz önemli işlere odaklansın.
          </AnimatedText>
        </div>

        {/* Workflow diagram */}
        <svg
          width={600}
          height={700}
          viewBox="0 0 600 700"
          style={{ position: "absolute", top: 520, left: "50%", marginLeft: -300 }}
        >
          {/* Connection lines between nodes */}
          {[0, 1, 2].map((i) => {
            const progress = lineDrawProgress(nodes[i].delay);
            const y1 = nodes[i].y - 520 + 30;
            const y2 = nodes[i + 1].y - 520 - 30;
            const pathLength = y2 - y1;

            return (
              <g key={`line-${i}`}>
                {/* Track line */}
                <line
                  x1={300}
                  y1={y1}
                  x2={300}
                  y2={y2}
                  stroke="#E5E5E7"
                  strokeWidth={2}
                  strokeDasharray="6 4"
                />
                {/* Animated progress line */}
                <line
                  x1={300}
                  y1={y1}
                  x2={300}
                  y2={y1 + pathLength * progress}
                  stroke="#0A0A0A"
                  strokeWidth={2}
                />
                {/* Flowing dot */}
                {progress > 0 && (
                  <circle
                    cx={300}
                    cy={y1 + pathLength * ((frame * 0.02 + i * 0.3) % 1)}
                    r={3}
                    fill="#0A0A0A"
                    opacity={0.5}
                  />
                )}
              </g>
            );
          })}

          {/* Nodes */}
          {nodes.map((node, i) => {
            const f = Math.max(0, frame - node.delay);
            const nodeScale = spring({
              frame: f, fps, from: 0, to: 1,
              config: { stiffness: 100, damping: 14 },
            });
            const nodeOpacity = interpolate(f, [0, 10], [0, 1], { extrapolateRight: "clamp" });

            // Glow when cascade reaches this node
            const glowIntensity = Math.max(0, 1 - Math.abs(cascadePhase - i) * 1.5);

            const cy = node.y - 520;
            return (
              <g
                key={`node-${i}`}
                transform={`translate(300, ${cy}) scale(${nodeScale})`}
                opacity={nodeOpacity}
              >
                {/* Glow ring */}
                <circle r={38} fill="none" stroke="#0A0A0A" strokeWidth={1}
                  opacity={glowIntensity * 0.4}
                  transform={`scale(${1 + glowIntensity * 0.3})`}
                />
                {/* Node circle */}
                <circle r={28} fill="#FAFAFA" stroke="#0A0A0A" strokeWidth={1.5} />
                {/* Icon */}
                <text
                  textAnchor="middle"
                  dy={2}
                  fontSize={18}
                  fill="#0A0A0A"
                >
                  {node.icon}
                </text>
                {/* Label */}
                <text
                  textAnchor="middle"
                  dy={52}
                  fontSize={16}
                  fontWeight={600}
                  fill="#1D1D1F"
                  fontFamily={fontFamily}
                >
                  {node.label}
                </text>
              </g>
            );
          })}
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
