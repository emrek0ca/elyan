import React from "react";
import {DepthBackground} from "../components/DepthBackground";
import {MotionTitle} from "../components/MotionTitle";
import {WorkflowRibbon} from "../components/WorkflowRibbon";
import {ParticleField} from "../components/ParticleField";

export const Scene3Execute: React.FC = () => {
  return (
    <>
      <DepthBackground mode="teal" />
      <MotionTitle text="From signal to action." y={208} size={78} color="#071015" align="left" width={780} />
      <WorkflowRibbon y={620} label="Observe incoming work" />
      <WorkflowRibbon y={780} label="Think through the route" accent="#84c7d0" />
      <WorkflowRibbon y={940} label="Plan the next exact step" accent="#92d7de" />
      <WorkflowRibbon y={1100} label="Execute with clean handoff" accent="#a6e2e7" />
      <ParticleField count={24} centerX={840} centerY={820} spread={340} opacity={0.38} />
    </>
  );
};
