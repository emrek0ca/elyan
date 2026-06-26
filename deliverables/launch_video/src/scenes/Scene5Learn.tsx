import React from "react";
import {DepthBackground} from "../components/DepthBackground";
import {MemoryOrbit} from "../components/MemoryOrbit";
import {ParticleField} from "../components/ParticleField";
import {RobotSequence} from "../components/RobotSequence";
import {LaunchVideoProps} from "../lib/assets";

export const Scene5Learn: React.FC<Pick<LaunchVideoProps, "scene5RobotSrc">> = ({scene5RobotSrc}) => {
  return (
    <>
      <DepthBackground mode="light" />
      <div
        style={{
          position: "absolute",
          left: 190,
          top: 270,
          width: 700,
          height: 700,
          borderRadius: 999,
          background: "radial-gradient(circle, rgba(185,237,241,0.72) 0%, rgba(110,184,196,0.18) 38%, rgba(110,184,196,0) 72%)",
        }}
      />
      <MemoryOrbit centerX={540} centerY={770} />
      <ParticleField count={30} centerX={540} centerY={820} spread={360} opacity={0.65} />
      <RobotSequence src={scene5RobotSrc} width={520} x={270} y={560} fromX={0} fromY={120} tilt={0} />
    </>
  );
};
