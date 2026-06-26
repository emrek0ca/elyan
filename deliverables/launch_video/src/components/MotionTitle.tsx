import React from "react";
import {interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {palette} from "../lib/palette";

type MotionTitleProps = {
  text: string;
  y: number;
  size?: number;
  align?: "left" | "center";
  color?: string;
  width?: number;
  delay?: number;
};

export const MotionTitle: React.FC<MotionTitleProps> = ({
  text,
  y,
  size = 88,
  align = "center",
  color = palette.ink,
  width = 860,
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({fps, frame: frame - delay, config: {damping: 18, stiffness: 120}});
  const opacity = interpolate(enter, [0, 0.3, 1], [0, 0.4, 1]);
  const translateY = interpolate(enter, [0, 1], [44, 0]);
  const blur = interpolate(enter, [0, 1], [24, 0]);
  return (
    <div
      style={{
        position: "absolute",
        top: y,
        left: align === "center" ? 110 : 98,
        width,
        textAlign: align,
        fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
        fontSize: size,
        fontWeight: 500,
        letterSpacing: -3.6,
        lineHeight: 0.96,
        color,
        opacity,
        transform: `translateY(${translateY}px)`,
        filter: `blur(${blur}px)`,
      }}
    >
      {text}
    </div>
  );
};
