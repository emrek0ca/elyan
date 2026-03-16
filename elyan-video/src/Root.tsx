import React from "react";
import { Composition, Sequence, AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { Scene1Intro } from "./scenes/Scene1Intro";
import { Scene2Problem } from "./scenes/Scene2Problem";
import { Scene3Agents } from "./scenes/Scene3Agents";
import { Scene4Automation } from "./scenes/Scene4Automation";
import { Scene5Integration } from "./scenes/Scene5Integration";
import { Scene6Robot } from "./scenes/Scene6Robot";
import { Scene7CTA } from "./scenes/Scene7CTA";

/**
 * ELYAN Promo Video — 60s @ 30fps = 1800 frames
 * Format: 1080x1920 (9:16 vertical / story)
 *
 * Scene timeline:
 * 1. Intro/Logo       0–150   (0–5s)
 * 2. Problem         150–360  (5–12s)
 * 3. AI Agents       360–660  (12–22s)
 * 4. Automation      660–990  (22–33s)
 * 5. Integration     990–1290 (33–43s)
 * 6. Robot Showcase 1290–1560 (43–52s)
 * 7. CTA/Outro      1560–1800 (52–60s)
 *
 * Cross-fade overlap: 15 frames between scenes
 */

const CROSS_FADE = 15;

const ElyanPromo: React.FC = () => {
  const frame = useCurrentFrame();

  return (
    <AbsoluteFill style={{ background: "#FFFFFF", overflow: "hidden" }}>
      {/* Scene 1: Intro */}
      <Sequence from={0} durationInFrames={150 + CROSS_FADE} name="Intro">
        <FadeWrapper sceneFrame={frame} sceneStart={0} sceneDuration={150} crossFade={CROSS_FADE}>
          <Scene1Intro />
        </FadeWrapper>
      </Sequence>

      {/* Scene 2: Problem */}
      <Sequence from={150 - CROSS_FADE} durationInFrames={210 + CROSS_FADE * 2} name="Problem">
        <FadeWrapper sceneFrame={frame} sceneStart={150} sceneDuration={210} crossFade={CROSS_FADE}>
          <Scene2Problem />
        </FadeWrapper>
      </Sequence>

      {/* Scene 3: AI Agents */}
      <Sequence from={360 - CROSS_FADE} durationInFrames={300 + CROSS_FADE * 2} name="AI Agents">
        <FadeWrapper sceneFrame={frame} sceneStart={360} sceneDuration={300} crossFade={CROSS_FADE}>
          <Scene3Agents />
        </FadeWrapper>
      </Sequence>

      {/* Scene 4: Automation */}
      <Sequence from={660 - CROSS_FADE} durationInFrames={330 + CROSS_FADE * 2} name="Automation">
        <FadeWrapper sceneFrame={frame} sceneStart={660} sceneDuration={330} crossFade={CROSS_FADE}>
          <Scene4Automation />
        </FadeWrapper>
      </Sequence>

      {/* Scene 5: Integration */}
      <Sequence from={990 - CROSS_FADE} durationInFrames={300 + CROSS_FADE * 2} name="Integration">
        <FadeWrapper sceneFrame={frame} sceneStart={990} sceneDuration={300} crossFade={CROSS_FADE}>
          <Scene5Integration />
        </FadeWrapper>
      </Sequence>

      {/* Scene 6: Robot Showcase */}
      <Sequence from={1290 - CROSS_FADE} durationInFrames={270 + CROSS_FADE * 2} name="Robot Showcase">
        <FadeWrapper sceneFrame={frame} sceneStart={1290} sceneDuration={270} crossFade={CROSS_FADE}>
          <Scene6Robot />
        </FadeWrapper>
      </Sequence>

      {/* Scene 7: CTA */}
      <Sequence from={1560 - CROSS_FADE} durationInFrames={240 + CROSS_FADE} name="CTA">
        <FadeWrapper sceneFrame={frame} sceneStart={1560} sceneDuration={240} crossFade={CROSS_FADE} isLast>
          <Scene7CTA />
        </FadeWrapper>
      </Sequence>
    </AbsoluteFill>
  );
};

/** Cross-fade wrapper — handles smooth fade in/out between scenes */
const FadeWrapper: React.FC<{
  children: React.ReactNode;
  sceneFrame: number;
  sceneStart: number;
  sceneDuration: number;
  crossFade: number;
  isLast?: boolean;
}> = ({ children, sceneFrame, sceneStart, sceneDuration, crossFade, isLast }) => {
  const localFrame = sceneFrame - sceneStart + crossFade;

  const fadeIn = interpolate(localFrame, [0, crossFade], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  const fadeOut = isLast
    ? 1
    : interpolate(
        localFrame,
        [sceneDuration, sceneDuration + crossFade],
        [1, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
      );

  return (
    <AbsoluteFill style={{ opacity: fadeIn * fadeOut }}>
      {children}
    </AbsoluteFill>
  );
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="ElyanPromo"
        component={ElyanPromo}
        durationInFrames={1800}
        fps={30}
        width={1080}
        height={1920}
      />
    </>
  );
};
