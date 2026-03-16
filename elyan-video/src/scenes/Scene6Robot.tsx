import React from "react";
import {
  AbsoluteFill, useCurrentFrame, useVideoConfig,
  spring, interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { Particles, CinematicGrid, ImpactText, AnimatedText, VFX, ReflectiveGlass, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene6Robot: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const useCases = [
    { label: "GÖREV PLANLAMA", y: -400 * scale, z: 200 * scale, color: "#0071E3" },
    { label: "DERİN ARAŞTIRMA", y: -150 * scale, z: 0, color: "#0A0A0A" },
    { label: "OPERASYONLAR", y: 100 * scale, z: -200 * scale, color: "#0071E3" },
    { label: "OTOMASYON", y: 350 * scale, z: 300 * scale, color: "#1D1D1F" },
  ];

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={100} colors={["#0071E3", "#0A0A0A"]} speed={0.8} />

        <AnamorphicFlare y={50 * scale} color="#0071E3" opacity={0.3} width={1800 * scale} />
        <AnamorphicFlare y={20 * scale} color="#0A0A0A" opacity={0.1} width={1000 * scale} />

        <LiquidBlob x={900 * scale} y={300 * scale} size={850 * scale} color="#0071E3" opacity={0.1} z={-250 * scale} />
        <LiquidBlob x={100 * scale} y={1700 * scale} size={950 * scale} color="#0A0A0A" opacity={0.08} z={-350 * scale} />

        <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: `0 ${80 * scale}px` }}>
          
          <div style={{ position: "absolute", zIndex: 100, textAlign: "center", top: 120 * scale }}>
            <ImpactText delay={10 * timeScale} fontSize={100 * scale} letterSpacing={6 * scale} color="#0A0A0A">
              GERÇEK
            </ImpactText>
            <ImpactText delay={20 * timeScale} fontSize={100 * scale} letterSpacing={6 * scale} color="#0A0A0A">
              VERİMLİLİK.
            </ImpactText>
            <div style={{ height: 25 * scale }} />
            <div style={{ display: "flex", justifyContent: "center" }}>
              <AnimatedText delay={45 * timeScale} animation="perChar" fontSize={30 * scale} fontWeight={400} color="#6E6E73" letterSpacing={12 * scale} textTransform="uppercase">
                Fikirlerden kusursuz eyleme.
              </AnimatedText>
            </div>
          </div>

          <div style={{
            position: "relative", width: "100%", height: "100%",
            perspective: 2500 * scale,
            transformStyle: "preserve-3d",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {useCases.map((useCase, i) => {
              const delay = (45 + i * 12) * timeScale;
              const f = Math.max(0, frame - delay);
              const entrance = spring({ frame: f, fps, config: { stiffness: 130, damping: 25 } });
              
              const float = Math.sin(frame * 0.04 + i) * (25 * scale);
              const opacity = interpolate(f, [0, 25], [0, 1]);

              return (
                <div key={i} style={{
                  position: "absolute",
                  transform: `
                    translateY(${useCase.y + float}px) 
                    translateZ(${useCase.z + (1 - entrance) * (-1800 * scale)}px)
                    rotateY(${interpolate(entrance, [0, 1], [15, 0])}deg)
                    rotateX(${interpolate(entrance, [0, 1], [-10, 0])}deg)
                  `,
                  opacity,
                  transformStyle: "preserve-3d",
                }}>
                  <ReflectiveGlass depth={50} style={{
                    padding: `${25 * scale}px ${45 * scale}px`,
                    borderRadius: 35 * scale,
                    width: 520 * scale,
                    display: "flex", alignItems: "center", gap: 25 * scale,
                    borderLeft: `${10 * scale}px solid ${useCase.color}`,
                    background: "rgba(255, 255, 255, 0.95)",
                    border: `${2 * scale}px solid rgba(255,255,255,1)`,
                    boxShadow: `0 ${40 * scale}px ${80 * scale}px rgba(0,0,0,0.15), 0 0 ${20 * scale}px ${useCase.color}20`,
                  }}>
                    <div style={{ fontSize: 34 * scale, fontWeight: 900, color: "#0A0A0A", letterSpacing: 3 * scale }}>
                      {useCase.label}
                    </div>
                  </ReflectiveGlass>
                </div>
              );
            })}
          </div>

          <div style={{
            position: "absolute", bottom: 150 * scale,
            transform: `translateZ(${500 * scale}px)`,
            opacity: 0.95,
            textAlign: "center",
          }}>
            <AnimatedText delay={130 * timeScale} animation="perChar" fontSize={28} fontWeight={600} color="#0071E3" letterSpacing={12} textTransform="uppercase">
              DAHA HIZLI. DAHA AKILLI. DAHA KESKİN.
            </AnimatedText>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    </VFX>
  );
};
