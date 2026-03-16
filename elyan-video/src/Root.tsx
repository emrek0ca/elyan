import React from "react";
import { Composition, Sequence, AbsoluteFill, interpolate, useCurrentFrame, spring, useVideoConfig, Audio, staticFile } from "remotion";
import { Scene1Intro } from "./scenes/Scene1Intro";
import { Scene2Problem } from "./scenes/Scene2Problem";
import { Scene3Agents } from "./scenes/Scene3Agents";
import { Scene4Automation } from "./scenes/Scene4Automation";
import { Scene5Integration } from "./scenes/Scene5Integration";
import { Scene6Robot } from "./scenes/Scene6Robot";
import { Scene7CTA } from "./scenes/Scene7CTA";
import { VFXStack, Stage3D, CinematicPostProcessing, AnamorphicFlare } from "./components/AnimatedText";

const OVERLAP = 40;
import { Scene8Scale } from "./scenes/Scene8Scale";

/** High-End Flagship Continuous camera Orchestrator - Cinematic Elite */
const SceneFlyThrough: React.FC<{
  children: React.ReactNode;
  duration: number;
  isFirst?: boolean;
  isLast?: boolean;
}> = ({ children, duration, isFirst, isLast }) => {
  const frame = useCurrentFrame();
  const { fps, width } = useVideoConfig();
  const scaleFactor = width / 1080;

  // Premium Launch Film Easing - Snappy yet controlled
  const progress = spring({
    frame,
    fps,
    config: { stiffness: 120, damping: 28, mass: 0.8 },
  });

  const exit = spring({
    frame: Math.max(0, frame - (duration - OVERLAP)),
    fps,
    config: { stiffness: 100, damping: 32, mass: 1 },
  });

  // Cinematic Elite Bezier Pathing - Glitch-Free
  const z = (interpolate(progress, [0, 1], [-5000, 0]) + interpolate(exit, [0, 1], [0, 7000])) * scaleFactor;
  const scale = interpolate(progress, [0, 1], [0.4, 1]) * interpolate(exit, [0, 1], [1, 4]);
  
  // Smoother cross-fade overlap
  const opacity = interpolate(progress, [0, 0.5], [0, 1]) * interpolate(exit, [0.5, 1], [1, 0]);
  
  // Dynamic Focal Simulation
  const blur = interpolate(Math.abs(z), [0, 1200 * scaleFactor], [0, 30 * scaleFactor], { extrapolateLeft: "clamp" });
  
  // Elite Multi-Axis Rotation
  const rotateX = interpolate(progress, [0, 1], [25, 0]) + interpolate(exit, [0, 1], [0, -30]);
  const rotateY = interpolate(progress, [0, 1], [-15, 0]) + interpolate(exit, [0, 1], [0, 20]);
  const rotateZ = interpolate(progress, [0, 0.5, 1], [10, -5, 0]) + interpolate(exit, [0, 1], [0, 8]);

  return (
    <AbsoluteFill style={{ 
      opacity, 
      pointerEvents: "none",
      filter: `blur(${blur}px)`,
    }}>
      <Stage3D perspective={1200 * scaleFactor} rotateX={rotateX} rotateY={rotateY}>
        <div style={{
          transform: `translateZ(${z}px) scale(${scale}) rotateZ(${rotateZ}deg)`,
          width: "100%", height: "100%",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {children}
        </div>
      </Stage3D>
    </AbsoluteFill>
  );
};

export const ElyanPromo: React.FC = () => {
  return (
    <CinematicPostProcessing>
      <VFXStack>
        <AbsoluteFill style={{ backgroundColor: "#FBFBFB" }}>
          <AnamorphicFlare y={30} opacity={0.15} color="#0071E3" />
          
          <Sequence from={0} durationInFrames={440}>
            <SceneFlyThrough duration={440} isFirst><Scene1Intro /></SceneFlyThrough>
          </Sequence>

          <Sequence from={400} durationInFrames={480}>
            <SceneFlyThrough duration={480}><Scene2Problem /></SceneFlyThrough>
          </Sequence>

          <Sequence from={840} durationInFrames={520}>
            <SceneFlyThrough duration={520}><Scene3Agents /></SceneFlyThrough>
          </Sequence>

          <Sequence from={1320} durationInFrames={560}>
            <SceneFlyThrough duration={560}><Scene4Automation /></SceneFlyThrough>
          </Sequence>

          <Sequence from={1840} durationInFrames={520}>
            <SceneFlyThrough duration={520}><Scene5Integration /></SceneFlyThrough>
          </Sequence>

          <Sequence from={2320} durationInFrames={520}>
            <SceneFlyThrough duration={520}><Scene6Robot /></SceneFlyThrough>
          </Sequence>

          <Sequence from={2800} durationInFrames={520}>
            <SceneFlyThrough duration={520}><Scene7CTA /></SceneFlyThrough>
          </Sequence>

          <Sequence from={3280} durationInFrames={520}>
            <SceneFlyThrough duration={520}><Scene8Scale /></SceneFlyThrough>
          </Sequence>

          <Sequence from={3760} durationInFrames={1240}>
            <SceneFlyThrough duration={1240} isLast><Scene7CTA /></SceneFlyThrough>
          </Sequence>
          
          <Audio src={staticFile("launch_music.mp3")} />
        </AbsoluteFill>
      </VFXStack>
    </CinematicPostProcessing>
  );
};

export const RemotionRoot: React.FC = () => (
  <Composition
    id="ElyanPromo"
    component={ElyanPromo}
    durationInFrames={5000} 
    fps={60}
    width={2160}
    height={3840}
  />
);
