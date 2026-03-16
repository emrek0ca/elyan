import React from "react";
import {
  AbsoluteFill, useCurrentFrame, useVideoConfig,
  spring, interpolate,
} from "remotion";
import { loadFont } from "@remotion/google-fonts/Inter";
import { Particles, CinematicGrid, ImpactText, AnimatedText, VFX, ReflectiveGlass, LiquidBlob, AnamorphicFlare } from "../components/AnimatedText";

const { fontFamily } = loadFont();

export const Scene8Scale: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const timeScale = fps / 30;
  const scale = width / 1080;

  const metrics = [
    { label: "10x", sub: "VERİMLİLİK", y: -420 * scale },
    { label: "100%", sub: "OTONOM", y: 0 },
    { label: "KÜRESEL", sub: "YETENEK", y: 420 * scale },
  ];

  return (
    <VFX>
      <AbsoluteFill style={{ overflow: "hidden", fontFamily }}>
        <CinematicGrid opacity={0.015} />
        <Particles count={110} colors={["#0071E3", "#0A0A0A"]} speed={0.8} />

        <AnamorphicFlare y={50} color="#0071E3" opacity={0.3} width={1800 * scale} />

        <LiquidBlob x={200} y={300} size={800} color="#0071E3" opacity={0.1} z={-300} />
        <LiquidBlob x={900} y={1600} size={900} color="#0A0A0A" opacity={0.08} z={-250} />

        <AbsoluteFill style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: `0 ${80 * scale}px` }}>
          
          <div style={{ position: "absolute", top: 120 * scale, zIndex: 100, textAlign: "center" }}>
            <ImpactText delay={10 * timeScale} fontSize={100} letterSpacing={6} color="#0A0A0A">
              SINIRSIZ
            </ImpactText>
            <ImpactText delay={20 * timeScale} fontSize={100} letterSpacing={6} color="#0A0A0A">
              ÖLÇEKLENDİRME.
            </ImpactText>
          </div>

          <div style={{
            position: "relative", width: "100%", height: "100%",
            perspective: 2500 * scale,
            transformStyle: "preserve-3d",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {metrics.map((metric, i) => {
              const delay = (45 + i * 15) * timeScale;
              const f = Math.max(0, frame - delay);
              const entrance = spring({ frame: f, fps, config: { stiffness: 120, damping: 25 } });
              const opacity = interpolate(f, [0, 25], [0, 1]);
              const float = Math.sin(frame * 0.04 + i) * (25 * scale);

              return (
                <div key={i} style={{
                  position: "absolute",
                  transform: `
                    translateY(${metric.y + float}px) 
                    translateZ(${interpolate(entrance, [0, 1], [-2000 * scale, 0])}px)
                    scale(${interpolate(entrance, [0, 1], [0.6, 1])})
                    rotateX(${interpolate(entrance, [0, 1], [20, 0])}deg)
                    rotateZ(${interpolate(entrance, [0, 1], [-10, 0])}deg)
                  `,
                  opacity,
                  textAlign: "center",
                  transformStyle: "preserve-3d",
                }}>
                  <ImpactText fontSize={150} color={i === 1 ? "#0071E3" : "#0A0A0A"} delay={0}>
                    {metric.label}
                  </ImpactText>
                  <div style={{ marginTop: 30 * scale }}>
                    <AnimatedText delay={25 * timeScale} animation="perChar" fontSize={38} fontWeight={900} color="#6E6E73" letterSpacing={18} textTransform="uppercase">
                      {metric.sub}
                    </AnimatedText>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Elite Scaling Circles */}
          <div style={{ position: "absolute", transform: "rotateX(45deg)", transformStyle: "preserve-3d", zIndex: -1 }}>
            <svg width={width} height={height} style={{ opacity: 0.15, pointerEvents: "none" }}>
              <circle cx={width/2} cy={height/2} r={interpolate(frame * 1.6, [0, 300], [200 * scale, 1400 * scale])} stroke="#0071E3" strokeWidth={3 * scale} fill="none" />
              <circle cx={width/2} cy={height/2} r={interpolate(frame * 1.6, [0, 300], [150 * scale, 1200 * scale])} stroke="#0A0A0A" strokeWidth={1 * scale} fill="none" opacity={0.3} />
              <circle cx={width/2} cy={height/2} r={interpolate(frame * 1.6, [0, 300], [300 * scale, 1600 * scale])} stroke="#0071E3" strokeWidth={1 * scale} fill="none" opacity={0.1} />
            </svg>
          </div>
        </AbsoluteFill>
      </AbsoluteFill>
    </VFX>
  );
};
