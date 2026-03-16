import React from "react";
import {
  AbsoluteFill, useCurrentFrame, useVideoConfig,
  spring, interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { CinematicGrid, ImpactText, AnimatedText, VFX, ReflectiveGlass, Particles, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene2Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const cards = [
    { title: "VERİ ANALİZİ", delay: 15 * timeScale, color: "#0071E3" },
    { title: "İŞ AKIŞI", delay: 45 * timeScale, color: "#0A0A0A" },
    { title: "OTOMASYON", delay: 75 * timeScale, color: "#0071E3" },
  ];

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={90} colors={["#0071E3", "#0A0A0A"]} speed={0.5} />

        <AnamorphicFlare y={10} color="#0071E3" opacity={0.3} width={1800 * scale} />
        <AnamorphicFlare y={92} color="#0A0A0A" opacity={0.15} width={1200 * scale} />

        <LiquidBlob x={100} y={1500} size={700} color="#0071E3" opacity={0.1} z={-200} />
        <LiquidBlob x={900} y={300} size={800} color="#0A0A0A" opacity={0.08} z={-300} />

        <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: `0 ${80 * scale}px` }}>
          
          <div style={{ position: "absolute", top: 180 * scale, zIndex: 100, textAlign: "center" }}>
            <ImpactText delay={5 * timeScale} fontSize={90} letterSpacing={6} color="#0A0A0A">
              SADECE BİR
            </ImpactText>
            <ImpactText delay={15 * timeScale} fontSize={90} letterSpacing={6} color="#0A0A0A">
              SOHBET DEĞİL.
            </ImpactText>
            <div style={{ height: 25 * scale }} />
            <div style={{ display: "flex", justifyContent: "center" }}>
              <AnimatedText delay={40 * timeScale} animation="perChar" fontSize={30} fontWeight={400} color="#6E6E73" letterSpacing={10} textTransform="uppercase">
                Tam Kapsamlı AI Operasyon Sistemi
              </AnimatedText>
            </div>
          </div>

          <div style={{
            position: "relative", width: "100%", height: "100%",
            perspective: 2500 * scale,
            transformStyle: "preserve-3d",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {cards.map((card, i) => {
              const f = Math.max(0, frame - card.delay);
              const entrance = spring({ frame: f, fps, config: { stiffness: 110, damping: 25 } });
              const opacity = interpolate(f, [0, 20], [0, 1]);
              const float = Math.sin(frame * 0.04 + i) * (20 * scale);

              return (
                <div key={i} style={{
                  position: "absolute",
                  transform: `
                    translateY(${(-220 * scale + i * 300 * scale) + float}px) 
                    translateZ(${(1 - entrance) * (-1800 * scale) + (150 * scale - i * 80 * scale)}px)
                    rotateX(${interpolate(entrance, [0, 1], [-20, 0])}deg)
                    rotateY(${interpolate(entrance, [0, 1], [15, 0])}deg)
                  `,
                  opacity,
                  transformStyle: "preserve-3d",
                }}>
                  <ReflectiveGlass depth={40} style={{
                    padding: `${40 * scale}px ${60 * scale}px`,
                    borderRadius: 55 * scale,
                    width: 480 * scale, height: 250 * scale,
                    display: "flex", flexDirection: "column", justifyContent: "space-between",
                    background: "rgba(255, 255, 255, 0.9)",
                    border: `${2 * scale}px solid rgba(255,255,255,1)`,
                    boxShadow: `0 ${60 * scale}px ${120 * scale}px rgba(0,0,0,0.15)`,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 20 * scale }}>
                      <div style={{ width: 14 * scale, height: 14 * scale, borderRadius: "50%", background: card.color, boxShadow: `0 0 ${15 * scale}px ${card.color}` }} />
                      <div style={{ fontSize: 32, fontWeight: 800, color: "#1D1D1F", letterSpacing: 5 * scale, textTransform: "uppercase" }}>
                        {card.title}
                      </div>
                    </div>
                    
                    <div style={{ height: 6 * scale, width: "100%", background: "rgba(0,0,0,0.06)", borderRadius: 3 * scale, overflow: "hidden" }}>
                        <div style={{ width: `${entrance * 80}%`, height: "100%", background: card.color, opacity: 0.6 }} />
                    </div>
                    
                    <div style={{ display: "flex", flexDirection: "column", gap: 15 * scale }}>
                      <div style={{ height: 16 * scale, width: "100%", background: "rgba(0,0,0,0.04)", borderRadius: 5 * scale }} />
                      <div style={{ height: 16 * scale, width: "65%", background: "rgba(0,0,0,0.04)", borderRadius: 5 * scale }} />
                    </div>
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
