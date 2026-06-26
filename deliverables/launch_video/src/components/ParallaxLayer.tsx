import React from "react";
import {interpolate, useCurrentFrame} from "remotion";

type ParallaxLayerProps = {
  depth: number;
  x?: number;
  y?: number;
  scale?: number;
  opacity?: number;
  blur?: number;
  children: React.ReactNode;
};

export const ParallaxLayer: React.FC<ParallaxLayerProps> = ({
  depth,
  x = 0,
  y = 0,
  scale = 1,
  opacity = 1,
  blur = 0,
  children,
}) => {
  const frame = useCurrentFrame();
  const driftX = interpolate(frame, [0, 1800], [x, x - depth * 36], {extrapolateRight: "clamp"});
  const driftY = interpolate(frame, [0, 1800], [y, y - depth * 64], {extrapolateRight: "clamp"});
  const driftScale = interpolate(frame, [0, 1800], [scale, scale + depth * 0.06], {extrapolateRight: "clamp"});
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        transform: `translate3d(${driftX}px, ${driftY}px, 0) scale(${driftScale})`,
        opacity,
        filter: blur > 0 ? `blur(${blur}px)` : undefined,
        willChange: "transform, opacity",
      }}
    >
      {children}
    </div>
  );
};
