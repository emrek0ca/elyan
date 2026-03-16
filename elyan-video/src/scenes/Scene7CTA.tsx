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
import { Particles, CinematicGrid, ImpactText, AnimatedText, VFX, ReflectiveGlass, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene7CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const entrance = spring({
    frame,
    fps,
    config: { stiffness: 150, damping: 25 },
  });

  const float = Math.sin(frame * 0.04) * (25 * scale);

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={100} colors={["#0071E3", "#0A0A0A"]} speed={0.9} />

        <AnamorphicFlare y={50 * scale} color="#0071E3" opacity={0.3} width={1800 * scale} />
        <AnamorphicFlare y={82 * scale} color="#0A0A0A" opacity={0.15} width={1200 * scale} />

        <LiquidBlob x={540 * scale} y={960 * scale} size={1300 * scale} color="#0071E3" opacity={0.1} z={-250 * scale} />
        <LiquidBlob x={100 * scale} y={1800 * scale} size={800 * scale} color="#0A0A0A" opacity={0.08} z={-300 * scale} />

        <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: `0 ${80 * scale}px` }}>
          
          {/* Elite Hero Scale-Up Reveal */}
          <div style={{
            transform: `
              translateY(${float}px) 
              translateZ(${400 * scale}px) 
              scale(${interpolate(entrance, [0, 1], [0.7, 1])})
              rotateY(${interpolate(entrance, [0, 1], [15, 0])}deg)
            `,
            opacity: entrance,
            marginBottom: 100 * scale,
          }}>
            <ReflectiveGlass depth={60} style={{ width: 560 * scale, borderRadius: 140 * scale, overflow: "hidden", boxShadow: `0 ${60 * scale}px ${140 * scale}px rgba(0,0,0,0.25)` }}>
              <Img src={staticFile("elyanRobot.png")} style={{ width: "100%", height: "auto" }} />
            </ReflectiveGlass>
          </div>

          <div style={{ textAlign: "center", zIndex: 100 }}>
            <ImpactText delay={25 * timeScale} fontSize={160 * scale} letterSpacing={8 * scale} color="#0A0A0A">
              ELYAN
            </ImpactText>
            <div style={{ height: 35 * scale }} />
            <AnimatedText delay={60 * timeScale} animation="perChar" fontSize={34 * scale} fontWeight={400} color="#6E6E73" letterSpacing={12 * scale} textTransform="uppercase">
              POTANSİYELİNİZİ ARTIRIN.
            </AnimatedText>
            
            <div style={{ 
              marginTop: 120 * scale,
              transform: `translateY(${interpolate(entrance, [0, 1], [80 * scale, 0])}px)`,
              opacity: interpolate(entrance, [0.7, 1], [0, 1]),
            }}>
              <ReflectiveGlass style={{
                padding: `${28 * scale}px ${80 * scale}px`,
                borderRadius: 55 * scale,
                background: "#0A0A0A",
                border: `${2 * scale}px solid rgba(255,255,255,0.1)`,
                boxShadow: `0 ${40 * scale}px ${80 * scale}px rgba(0,0,0,0.3)`,
              }}>
                <span style={{ color: "#FFFFFF", fontSize: 28 * scale, fontWeight: 900, letterSpacing: 6 * scale }}>
                  HEMEN BAŞLAYIN
                </span>
              </ReflectiveGlass>
            </div>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    </VFX>
  );
};
