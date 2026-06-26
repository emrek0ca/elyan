import React from "react";
import {DepthBackground} from "../components/DepthBackground";
import {DeviceCluster} from "../components/DeviceCluster";
import {SignalPulse} from "../components/SignalPulse";

export const Scene6Converge: React.FC = () => {
  return (
    <>
      <DepthBackground mode="teal" />
      <DeviceCluster />
      <div
        style={{
          position: "absolute",
          left: 420,
          top: 700,
          width: 240,
          height: 240,
          borderRadius: 999,
          background: "radial-gradient(circle, rgba(185,237,241,0.92) 0%, rgba(110,184,196,0.34) 36%, rgba(110,184,196,0) 74%)",
        }}
      />
      <SignalPulse x={540} y={820} size={28} />
    </>
  );
};
