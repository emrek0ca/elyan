import React from "react";
import {Img, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {palette} from "../lib/palette";

type HeroOutroProps = {
  logoSrc: string;
};

export const HeroOutro: React.FC<HeroOutroProps> = ({logoSrc}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const settle = spring({fps, frame, config: {damping: 18, stiffness: 90}});
  const titleOpacity = interpolate(settle, [0, 0.3, 1], [0, 0.6, 1]);
  const translateY = interpolate(settle, [0, 1], [32, 0]);
  return (
    <>
      <Img
        src={logoSrc}
        style={{
          position: "absolute",
          left: 355,
          top: 420,
          width: 370,
          height: 370,
          objectFit: "contain",
          filter: "drop-shadow(0 22px 40px rgba(7,16,21,0.08))",
          transform: `translateY(${translateY}px)`,
          opacity: titleOpacity,
        }}
      />
      <div
        style={{
          position: "absolute",
          top: 1140,
          width: "100%",
          textAlign: "center",
          fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
          fontSize: 94,
          fontWeight: 500,
          color: palette.ink,
          letterSpacing: -4.2,
          opacity: titleOpacity,
          transform: `translateY(${translateY}px)`,
        }}
      >
        Elyan
      </div>
      <div
        style={{
          position: "absolute",
          top: 1288,
          width: "100%",
          textAlign: "center",
          fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif',
          fontSize: 44,
          fontWeight: 430,
          color: "rgba(7,16,21,0.66)",
          letterSpacing: -0.8,
          opacity: titleOpacity,
          transform: `translateY(${translateY}px)`,
        }}
      >
        AI that gets work done.
      </div>
    </>
  );
};
