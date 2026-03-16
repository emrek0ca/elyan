import React from "react";
import {
  AbsoluteFill, useCurrentFrame, useVideoConfig,
  spring, interpolate, Img, staticFile
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { Particles, CinematicGrid, ImpactText, AnimatedText, VFX, ReflectiveGlass, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene4Automation: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const agents = [
    { label: "PLANLAYICI", color: "#0071E3" },
    { label: "ARAŞTIRMACI", color: "#1D1D1F" },
    { label: "YAZAR", color: "#6E6E73" },
    { label: "SİSTEM", color: "#0071E3" },
    { label: "DENETLEYİCİ", color: "#1D1D1F" },
  ];

  const coreEntrance = spring({ frame, fps, config: { stiffness: 130, damping: 25 } });
  const rotate = frame * 1.8; // High-speed spin for elite feel

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={110} colors={["#0071E3", "#0A0A0A"]} speed={0.9} />
        
        <LiquidBlob x={540} y={960} size={1200} color="#0071E3" opacity={0.08} z={-300} />
        <LiquidBlob x={0} y={1920} size={800} color="#0A0A0A" opacity={0.06} z={-250} />

        <AnamorphicFlare y={80} color="#0071E3" opacity={0.2} width={1400 * scale} />

        <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: `0 ${60 * scale}px` }}>
          
          <div style={{ position: "absolute", top: 180 * scale, zIndex: 100, textAlign: "center" }}>
            <ImpactText delay={10 * timeScale} fontSize={90} letterSpacing={4} color="#0A0A0A">
              ÇOKLU-AJAN
            </ImpactText>
            <ImpactText delay={20 * timeScale} fontSize={90} letterSpacing={4} color="#0A0A0A">
              ZEKASI
            </ImpactText>
            <div style={{ height: 25 * scale }} />
            <div style={{ display: "flex", justifyContent: "center" }}>
              <AnimatedText delay={45 * timeScale} animation="perChar" fontSize={30} fontWeight={400} color="#6E6E73" letterSpacing={10} textTransform="uppercase">
                Tek sistem. Kusursuz koordinasyon.
              </AnimatedText>
            </div>
          </div>

          <div style={{
            position: "relative", width: "100%", height: "100%",
            perspective: 2500 * scale,
            transformStyle: "preserve-3d",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {/* Elite Multi-Axis Orbital Paths */}
            <div style={{ 
              position: "absolute", width: 1000 * scale, height: 1000 * scale, 
              transform: "rotateX(65deg) rotateZ(20deg)",
              transformStyle: "preserve-3d",
            }}>
              <svg width={1000 * scale} height={1000 * scale} style={{ position: "absolute", opacity: 0.2, pointerEvents: "none" }}>
                <circle cx={500 * scale} cy={500 * scale} r={440 * scale} stroke="#0071E3" strokeWidth={2 * scale} fill="none" />
                <circle cx={500 * scale} cy={500 * scale} r={400 * scale} stroke="#0A0A0A" strokeWidth={1 * scale} fill="none" opacity={0.4} />
              </svg>
            </div>

            {/* High-End Central Core - Elite Materials */}
            <div style={{
              transform: `scale(${coreEntrance * 1.05}) translateZ(${300 * scale}px) rotateY(${rotate}deg)`,
              zIndex: 100,
            }}>
              <ReflectiveGlass depth={40} style={{ width: 280 * scale, height: 280 * scale, borderRadius: 80 * scale, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: `0 ${50 * scale}px ${100 * scale}px rgba(0,0,0,0.2)` }}>
                <Img src={staticFile("elyanRobot.png")} style={{ width: 180 * scale, height: "auto" }} />
              </ReflectiveGlass>
            </div>

            {/* Orbital Expert Modules - Elite Spacing */}
            {agents.map((agent, i) => {
              const delay = (40 + i * 10) * timeScale;
              const f = Math.max(0, frame - delay);
              const orbitAngle = (i / agents.length) * Math.PI * 2 + (frame * 0.045); // Elite high-speed orbit
              
              const radiusEntrance = interpolate(f, [0, 40], [1800 * scale, 440 * scale], { extrapolateRight: "clamp" });
              
              // Tilted Planetarium Transform
              const tx = Math.cos(orbitAngle) * radiusEntrance;
              const ty = Math.sin(orbitAngle) * radiusEntrance * 0.42; // Tilted Y
              const tz = Math.sin(orbitAngle) * (450 * scale);

              const slide = spring({ frame: f, fps, config: { stiffness: 150, damping: 25 } });
              const opacity = interpolate(f, [0, 20], [0, 1]);

              return (
                <div key={i} style={{
                  position: "absolute",
                  transform: `translate(calc(-50% + ${tx}px), calc(-50% + ${ty}px)) translateZ(${tz}px)`,
                  opacity: opacity * slide,
                  zIndex: Math.round(tz + 2000 * scale),
                  transformStyle: "preserve-3d",
                }}>
                  <ReflectiveGlass style={{
                    padding: `${22 * scale}px ${38 * scale}px`, borderRadius: 45 * scale,
                    display: "flex", alignItems: "center", gap: 18 * scale,
                    background: "rgba(255, 255, 255, 0.95)",
                    border: `${2 * scale}px solid rgba(255,255,255,1)`,
                    width: "max-content",
                    boxShadow: `0 ${30 * scale}px ${60 * scale}px rgba(0,0,0,0.15)`,
                  }}>
                    <div style={{ width: 12 * scale, height: 12 * scale, borderRadius: "50%", background: agent.color, boxShadow: `0 0 ${15 * scale}px ${agent.color}` }} />
                    <span style={{ fontSize: 26 * scale, fontWeight: 800, letterSpacing: 4 * scale, color: "#0A0A0A" }}>
                      {agent.label}
                    </span>
                  </ReflectiveGlass>
                </div>
              );
            })}
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    </VFX>
  );
};
