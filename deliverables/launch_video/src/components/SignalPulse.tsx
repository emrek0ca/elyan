import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {palette} from "../lib/palette";

type SignalPulseProps = {
  x: number;
  y: number;
  size?: number;
  color?: string;
};

export const SignalPulse: React.FC<SignalPulseProps> = ({x, y, size = 44, color = palette.teal}) => {
  const frame = useCurrentFrame();
  const wave = frame % 60;
  const scale = interpolate(wave, [0, 60], [0.3, 2.2]);
  const opacity = interpolate(wave, [0, 12, 60], [0, 0.5, 0]);
  return (
    <>
      <div
        style={{
          position: "absolute",
          left: x - size / 2,
          top: y - size / 2,
          width: size,
          height: size,
          borderRadius: 999,
          background: color,
          boxShadow: `0 0 30px ${palette.glow}`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: x - size / 2,
          top: y - size / 2,
          width: size,
          height: size,
          borderRadius: 999,
          border: `1px solid ${color}`,
          opacity,
          transform: `scale(${scale})`,
        }}
      />
    </>
  );
};
