import React from "react";
import {CameraRig} from "../components/CameraRig";
import {DepthBackground} from "../components/DepthBackground";
import {ParticleField} from "../components/ParticleField";
import {RobotSequence} from "../components/RobotSequence";
import {SignalPulse} from "../components/SignalPulse";
import {ParallaxLayer} from "../components/ParallaxLayer";
import {LaunchVideoProps} from "../lib/assets";

export const Scene2Observe: React.FC<Pick<LaunchVideoProps, "scene2RobotSrc">> = ({scene2RobotSrc}) => {
  return (
    <>
      <DepthBackground mode="light" />
      <CameraRig fromScale={1.08} toScale={1} fromX={40} toX={-20} fromY={20} toY={-24}>
        <ParallaxLayer depth={0.26}>
          <div
            style={{
              position: "absolute",
              left: 130,
              top: 340,
              width: 340,
              height: 340,
              borderRadius: 999,
              border: "1px solid rgba(34,65,76,0.08)",
            }}
          />
        </ParallaxLayer>
        <ParticleField count={18} centerX={310} centerY={620} spread={240} opacity={0.7} />
        <RobotSequence src={scene2RobotSrc} width={690} x={350} y={580} fromX={180} fromY={140} tilt={-6} />
        <SignalPulse x={308} y={614} size={30} />
        <SignalPulse x={255} y={840} size={22} />
      </CameraRig>
    </>
  );
};
