import React from "react";
import {
  AbsoluteFill, useCurrentFrame, useVideoConfig,
  spring, interpolate, staticFile,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { Particles, CinematicGrid, ImpactText, AnimatedText, VFX, ReflectiveGlass, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene5Integration: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const memoryBlocks = [
    { label: "PROJE BAĞLAMI", y: -450 * scale, z: -200 * scale },
    { label: "KULLANICI TERCİHLERİ", y: -150 * scale, z: 100 * scale },
    { label: "ÇALIŞMA ALIŞKANLIKLARI", y: 150 * scale, z: 400 * scale },
    { label: "KÜRESEL BİLGİ", y: 450 * scale, z: -400 * scale },
  ];

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={90} colors={["#0071E3", "#0A0A0A"]} speed={0.7} />

        <AnamorphicFlare y={50} color="#0071E3" opacity={0.25} width={1600 * scale} />
        <AnamorphicFlare y={90} color="#0A0A0A" opacity={0.1} width={800 * scale} />

        <LiquidBlob x={100} y={400} size={850} color="#0071E3" opacity={0.1} z={-350} />
        <LiquidBlob x={950} y={1500} size={750} color="#0A0A0A" opacity={0.08} z={-250} />

        <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: `0 ${80 * scale}px` }}>
          
          <div style={{ position: "absolute", top: 180 * scale, zIndex: 100, textAlign: "center" }}>
            <ImpactText delay={10 * timeScale} fontSize={90} letterSpacing={4} color="#0A0A0A">
              BAĞLAM
            </ImpactText>
            <ImpactText delay={20 * timeScale} fontSize={90} letterSpacing={4} color="#0A0A0A">
              VE BELLEK
            </ImpactText>
            <div style={{ height: 25 * scale }} />
            <div style={{ display: "flex", justifyContent: "center" }}>
              <AnimatedText delay={45 * timeScale} animation="perChar" fontSize={30} fontWeight={400} color="#6E6E73" letterSpacing={10} textTransform="uppercase">
                Sizinle birlikte öğrenen ve gelişen zeka.
              </AnimatedText>
            </div>
          </div>

          <div style={{
            position: "relative", width: "100%", height: "100%",
            perspective: 2500 * scale,
            transformStyle: "preserve-3d",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {/* Elite Data Vault Environment - Vertical Stack */}
            {memoryBlocks.map((block, i) => {
              const delay = (45 + i * 15) * timeScale;
              const f = Math.max(0, frame - delay);
              const entrance = spring({ frame: f, fps, config: { stiffness: 120, damping: 25 } });
              
              const float = Math.sin(frame * 0.04 + i) * (25 * scale);
              const opacity = interpolate(f, [0, 25], [0, 1]);

              return (
                <div key={i} style={{
                  position: "absolute",
                  transform: `
                    translateY(${block.y + float}px) 
                    translateZ(${block.z + (1 - entrance) * (-1800 * scale)}px)
                    rotateX(${interpolate(entrance, [0, 1], [-20, 0])}deg)
                    rotateY(${interpolate(entrance, [0, 1], [10, 0])}deg)
                  `,
                  opacity,
                  transformStyle: "preserve-3d",
                }}>
                  <ReflectiveGlass depth={30} style={{
                    padding: `${40 * scale}px ${55 * scale}px`,
                    borderRadius: 55 * scale,
                    width: 480 * scale, height: 250 * scale,
                    display: "flex", flexDirection: "column", justifyContent: "space-between",
                    background: "rgba(255, 255, 255, 0.85)",
                    border: `${2 * scale}px solid rgba(255,255,255,1)`,
                    boxShadow: `0 ${60 * scale}px ${120 * scale}px rgba(0,0,0,0.15)`,
                  }}>
                    <div style={{ fontSize: 32, fontWeight: 800, color: "#0A0A0A", letterSpacing: 5 * scale, textTransform: "uppercase" }}>
                      {block.label}
                    </div>
                    <div style={{ height: 6 * scale, width: "100%", background: "rgba(0,0,0,0.08)", borderRadius: 3 * scale, overflow: "hidden" }}>
                      <div style={{ 
                        width: `${entrance * 100}%`, height: "100%", background: "#0071E3",
                        boxShadow: `0 0 ${15 * scale}px rgba(0,113,227,0.5)`
                      }} />
                    </div>
                    <div style={{ display: "flex", gap: 20 * scale }}>
                      {[1, 2, 3, 4, 5].map(dot => (
                        <div key={dot} style={{ 
                          width: 14 * scale, height: 14 * scale, borderRadius: "50%", background: "#0071E3", 
                          opacity: 0.9, boxShadow: `0 0 ${12 * scale}px rgba(0,113,227,0.6)` 
                        }} />
                      ))}
                    </div>
                  </ReflectiveGlass>
                </div>
              );
            })}

            {/* Elite Multi-Bezier Data Flow */}
            <svg width={width} height={height} style={{ position: "absolute", opacity: 0.15, pointerEvents: "none", zIndex: -1 }}>
              <path 
                d={`M${width/2},${-100 * scale} C${width/2 + Math.sin(frame * 0.02) * (500 * scale)},${height * 0.2} ${width/2 - Math.cos(frame * 0.03) * (500 * scale)},${height * 0.8} ${width/2},${height + 100 * scale}`} 
                stroke="#0071E3" strokeWidth={3 * scale} fill="none" 
                strokeDasharray={`${20 * scale} ${40 * scale}`}
                strokeDashoffset={frame * -8}
              />
            </svg>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    </VFX>
  );
};
