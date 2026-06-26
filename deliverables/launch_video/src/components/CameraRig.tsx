import React from "react";
import {interpolate, useCurrentFrame} from "remotion";

type CameraRigProps = {
  fromScale?: number;
  toScale?: number;
  fromX?: number;
  toX?: number;
  fromY?: number;
  toY?: number;
  rotate?: number;
  children: React.ReactNode;
};

export const CameraRig: React.FC<CameraRigProps> = ({
  fromScale = 1,
  toScale = 1.05,
  fromX = 0,
  toX = 0,
  fromY = 0,
  toY = 0,
  rotate = 0,
  children,
}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(frame, [0, 180], [0, 1], {extrapolateRight: "clamp"});
  const translateX = interpolate(progress, [0, 1], [fromX, toX]);
  const translateY = interpolate(progress, [0, 1], [fromY, toY]);
  const scale = interpolate(progress, [0, 1], [fromScale, toScale]);
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        transform: `translate3d(${translateX}px, ${translateY}px, 0) scale(${scale}) rotate(${rotate}deg)`,
        willChange: "transform",
      }}
    >
      {children}
    </div>
  );
};
