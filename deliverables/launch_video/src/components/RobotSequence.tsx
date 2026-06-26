import React from "react";
import {Img, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";

type RobotSequenceProps = {
  src: string;
  width: number;
  x: number;
  y: number;
  fromX?: number;
  fromY?: number;
  tilt?: number;
  glow?: boolean;
};

export const RobotSequence: React.FC<RobotSequenceProps> = ({
  src,
  width,
  x,
  y,
  fromX = 80,
  fromY = 110,
  tilt = -5,
  glow = true,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({fps, frame, config: {damping: 16, stiffness: 120}});
  const idleY = Math.sin(frame / 18) * 12;
  const translateX = interpolate(enter, [0, 1], [fromX, 0]);
  const translateY = interpolate(enter, [0, 1], [fromY, 0]);
  const scale = interpolate(enter, [0, 1], [0.84, 1]);
  const opacity = interpolate(enter, [0, 0.2, 1], [0, 0.42, 1]);
  const blur = interpolate(enter, [0, 1], [18, 0]);
  const layers = [20, 12, 6];

  return (
    <div style={{position: "absolute", left: x, top: y, width, opacity}}>
      {layers.map((offset, index) => (
        <Img
          key={offset}
          src={src}
          style={{
            position: "absolute",
            width,
            transform: `translate(${translateX + offset}px, ${translateY + idleY + offset * 0.25}px) scale(${scale}) rotate(${tilt + index * 0.3}deg)`,
            filter: `blur(${blur + index * 3}px)`,
            opacity: 0.07 - index * 0.018,
          }}
        />
      ))}
      <div
        style={{
          position: "absolute",
          inset: -80,
          borderRadius: 999,
          background: glow ? "radial-gradient(circle, rgba(144,217,223,0.34) 0%, rgba(144,217,223,0.08) 36%, rgba(144,217,223,0) 72%)" : "transparent",
        }}
      />
      <Img
        src={src}
        style={{
          position: "absolute",
          width,
          transform: `translate(${translateX}px, ${translateY + idleY}px) scale(${scale}) rotate(${tilt}deg)`,
          filter: `drop-shadow(0 42px 42px rgba(12, 22, 28, 0.16))`,
        }}
      />
    </div>
  );
};
