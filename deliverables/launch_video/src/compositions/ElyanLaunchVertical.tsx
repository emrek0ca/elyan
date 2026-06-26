import React from "react";
import {AbsoluteFill, Audio, Sequence} from "remotion";
import {CinematicTransition} from "../components/CinematicTransition";
import {Scene1Hook} from "../scenes/Scene1Hook";
import {Scene2Observe} from "../scenes/Scene2Observe";
import {Scene3Execute} from "../scenes/Scene3Execute";
import {Scene4Desktop} from "../scenes/Scene4Desktop";
import {Scene5Learn} from "../scenes/Scene5Learn";
import {Scene6Converge} from "../scenes/Scene6Converge";
import {Scene7Outro} from "../scenes/Scene7Outro";
import {assetManifest, LaunchVideoProps} from "../lib/assets";
import {sceneSpecs} from "../lib/timing";

export const ElyanLaunchVertical: React.FC<LaunchVideoProps> = (props) => {
  return (
    <AbsoluteFill style={{backgroundColor: "#f7faf9"}}>
      <Sequence durationInFrames={180}>
        <Scene1Hook logoSrc={props.logoSrc} />
      </Sequence>
      <Sequence from={180} durationInFrames={300}>
        <Scene2Observe scene2RobotSrc={props.scene2RobotSrc} />
      </Sequence>
      <Sequence from={480} durationInFrames={300}>
        <Scene3Execute />
      </Sequence>
      <Sequence from={780} durationInFrames={300}>
        <Scene4Desktop />
      </Sequence>
      <Sequence from={1080} durationInFrames={300}>
        <Scene5Learn scene5RobotSrc={props.scene5RobotSrc} />
      </Sequence>
      <Sequence from={1380} durationInFrames={240}>
        <Scene6Converge />
      </Sequence>
      <Sequence from={1620} durationInFrames={180}>
        <Scene7Outro logoSrc={props.logoSrc} />
      </Sequence>

      {sceneSpecs.map((scene) => (
        <CinematicTransition key={scene.id} scene={scene} />
      ))}

      {props.mutedSafe !== false ? (
        <>
          <Sequence durationInFrames={36}>
            <Audio src={assetManifest.sfx.start} volume={0.3} />
          </Sequence>
          <Sequence from={220} durationInFrames={72}>
            <Audio src={assetManifest.sfx.think} volume={0.18} />
          </Sequence>
          <Sequence from={700} durationInFrames={54}>
            <Audio src={assetManifest.sfx.hud} volume={0.12} />
          </Sequence>
          <Sequence from={1640} durationInFrames={80}>
            <Audio src={assetManifest.sfx.done} volume={0.22} />
          </Sequence>
        </>
      ) : null}
    </AbsoluteFill>
  );
};
