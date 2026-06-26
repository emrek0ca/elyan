import React from "react";
import {Img, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";

type LogoRevealProps = {
  src: string;
  size?: number;
  centerY?: number;
};

export const LogoReveal: React.FC<LogoRevealProps> = ({src, size = 420, centerY = 760}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const reveal = spring({fps, frame, config: {damping: 17, stiffness: 90}});
  const scale = interpolate(reveal, [0, 1], [0.72, 1]);
  const mask = interpolate(reveal, [0, 1], [0, size * 0.7]);
  const opacity = interpolate(reveal, [0, 0.12, 1], [0, 0.35, 1]);
  return (
    <div
      style={{
        position: "absolute",
        left: 540 - size / 2,
        top: centerY - size / 2,
        width: size,
        height: size,
        opacity,
        transform: `scale(${scale})`,
        clipPath: `circle(${mask}px at 50% 50%)`,
        filter: "drop-shadow(0 18px 32px rgba(7,16,21,0.08))",
      }}
    >
      <Img src={src} style={{width: "100%", height: "100%", objectFit: "contain"}} />
    </div>
  );
};
