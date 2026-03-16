import React from "react";
import {
  AbsoluteFill, useCurrentFrame, useVideoConfig,
  spring, interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { Particles, CinematicGrid, ImpactText, AnimatedText, VFX, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene3Agents: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const concepts = [
    { label: "DÜŞÜN.", delay: 30 * timeScale, y: -450 * scale, z: 200 * scale, color: "#0A0A0A", sub: "VERİ ANALİZİ" },
    { label: "PLANLA.", delay: 70 * timeScale, y: 0, z: 0, color: "#0071E3", sub: "STRATEJİK PLANLAMA" },
    { label: "UYGULA.", delay: 110 * timeScale, y: 450 * scale, z: -200 * scale, color: "#0A0A0A", sub: "KESİNTİSİZ İCRAAT" },
  ];

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={90} colors={["#0071E3", "#0A0A0A"]} speed={0.6} />

        <AnamorphicFlare y={50 * scale} color="#0071E3" opacity={0.3} width={1800 * scale} />

        <LiquidBlob x={200 * scale} y={400 * scale} size={700 * scale} color="#0071E3" opacity={0.1} z={-250 * scale} />
        <LiquidBlob x={880 * scale} y={1500 * scale} size={800 * scale} color="#0A0A0A" opacity={0.08} z={-150 * scale} />

        <AbsoluteFill style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: `0 ${60 * scale}px` }}>
          
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
            width: "100%", height: "100%",
            transformStyle: "preserve-3d",
          }}>
            {concepts.map((concept, i) => {
              const f = Math.max(0, frame - concept.delay);
              const entrance = spring({ frame: f, fps, config: { stiffness: 110, damping: 22 } });
              const opacity = interpolate(f, [0, 15], [0, 1]);
              const float = Math.sin(frame * 0.05 + i) * (20 * scale);

              return (
                <div key={i} style={{
                  position: "absolute",
                  transform: `
                    translateY(${concept.y + float}px) 
                    translateZ(${concept.z + (1 - entrance) * (-1500 * scale)}px)
                    scale(${interpolate(entrance, [0, 1], [0.6, 1])})
                    rotateY(${interpolate(entrance, [0, 1], [-20, 0])}deg)
                    rotateZ(${interpolate(entrance, [0, 1], [-5, 0])}deg)
                  `,
                  opacity,
                  transformStyle: "preserve-3d",
                  textAlign: "center",
                }}>
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                    <ImpactText fontSize={140} letterSpacing={4} color={concept.color} delay={0}>
                      {concept.label}
                    </ImpactText>
                    
                    <div style={{ marginTop: 30 * scale, width: 320 * scale, height: 8 * scale, background: "rgba(0,0,0,0.08)", borderRadius: 4 * scale, overflow: "hidden" }}>
                      <div style={{ 
                        width: "100%", height: "100%", background: concept.color,
                        transform: `translateX(${(entrance - 1) * 100}%)`,
                        boxShadow: `0 0 ${15 * scale}px ${concept.color}`,
                      }} />
                    </div>

                    <div style={{ marginTop: 30 * scale }}>
                      <AnimatedText delay={20 * timeScale} animation="perChar" fontSize={28} fontWeight={600} color="#6E6E73" letterSpacing={12} textTransform="uppercase">
                        {concept.sub}
                      </AnimatedText>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <svg width={width} height={height} style={{ position: "absolute", opacity: 0.12, pointerEvents: "none", zIndex: -1 }}>
            <path 
              d={`M${width/2},0 Q${(440 * scale) + Math.sin(frame * 0.03) * (250 * scale)},${height/2} ${width/2},${height}`} 
              stroke="#0071E3" strokeWidth={4 * scale} fill="none" 
            />
          </svg>
        </AbsoluteFill>
      </AbsoluteFill>
    </VFX>
  );
};
