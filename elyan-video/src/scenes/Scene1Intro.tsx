import React from "react";
import {
  AbsoluteFill, Img, useCurrentFrame, useVideoConfig,
  spring, interpolate, staticFile,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { Particles, CinematicGrid, ImpactText, AnimatedText, VFX, ReflectiveGlass, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene1Intro: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const entrance = spring({ frame, fps, config: { stiffness: 60, damping: 20 } });
  const moveUp = spring({ frame: Math.max(0, frame - 150 * timeScale), fps, config: { stiffness: 50, damping: 22 } });

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={100} colors={["#0071E3", "#0A0A0A"]} speed={0.6} />
        
        <AnamorphicFlare y={45} color="#0071E3" opacity={0.25} width={1500 * scale} />
        <AnamorphicFlare y={85} color="#0A0A0A" opacity={0.1} width={800 * scale} />

        <LiquidBlob x={100} y={300} size={800} color="#0071E3" opacity={0.1} z={-250} />
        <LiquidBlob x={900} y={1600} size={900} color="#0A0A0A" opacity={0.08} z={-350} />

        <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: `0 ${60 * scale}px` }}>
          
          <div style={{
            transform: `
              translateY(${(1 - entrance) * (150 * scale) - moveUp * (500 * scale)}px) 
              translateZ(${entrance * (250 * scale)}px)
              rotateX(${moveUp * -5}deg)
            `,
            opacity: entrance,
            textAlign: "center"
          }}>
            <AnimatedText delay={20 * timeScale} animation="perChar" fontSize={30} fontWeight={400} color="#6E6E73" letterSpacing={14} textTransform="uppercase">
              GELECEK BURADA
            </AnimatedText>
            
            <div style={{ height: 35 * scale }} />
            
            <ImpactText delay={45 * timeScale} fontSize={150} letterSpacing={10} color="#0A0A0A">
              ELYAN
            </ImpactText>
            
            <div style={{ height: 45 * scale }} />
            
            <AnimatedText delay={90 * timeScale} animation="perChar" fontSize={28} fontWeight={600} color="#0071E3" letterSpacing={18} textTransform="uppercase">
              YAPAY ZEKA OPERATÖRÜ
            </AnimatedText>
          </div>

          <div style={{
            position: "absolute", bottom: -250 * scale,
            transform: `
              translateY(${(1 - moveUp) * (1000 * scale)}px) 
              translateZ(${500 * scale}px)
              rotateY(${interpolate(moveUp, [0, 1], [30, 0])}deg)
              rotateX(${interpolate(moveUp, [0, 1], [15, 0])}deg)
            `,
            opacity: moveUp,
          }}>
            <ReflectiveGlass style={{ width: 600 * scale, borderRadius: 140 * scale, overflow: "hidden", boxShadow: `0 ${60 * scale}px ${140 * scale}px rgba(0,0,0,0.15)` }}>
              <Img src={staticFile("elyanRobot.png")} style={{ width: "100%", height: "auto" }} />
            </ReflectiveGlass>
          </div>

          <svg width={width} height={height} style={{ position: "absolute", zIndex: -1, opacity: 0.12, pointerEvents: "none" }}>
            <path 
              d={`M${width/2},${height} C${width/2 + Math.sin(frame * 0.02) * (400 * scale)},${height * 0.72} ${width/2 - Math.cos(frame * 0.02) * (400 * scale)},${height * 0.26} ${width/2},0`} 
              stroke="#0071E3" strokeWidth={3 * scale} fill="none" 
            />
          </svg>
        </AbsoluteFill>
      </AbsoluteFill>
    </VFX>
  );
};
