import React from "react";
import {useCurrentFrame} from "remotion";
import {palette} from "../lib/palette";

type MemoryOrbitProps = {
  centerX: number;
  centerY: number;
};

export const MemoryOrbit: React.FC<MemoryOrbitProps> = ({centerX, centerY}) => {
  const frame = useCurrentFrame();
  return (
    <>
      {Array.from({length: 14}).map((_, index) => {
        const angle = (index / 14) * Math.PI * 2 + frame * 0.006 * (index % 3 === 0 ? 1 : -1);
        const radius = 180 + (index % 4) * 32;
        const x = centerX + Math.cos(angle) * radius;
        const y = centerY + Math.sin(angle) * radius * 0.58;
        const rotate = angle * 57.3;
        return (
          <div
            key={index}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: 36 + (index % 2) * 14,
              height: 10,
              borderRadius: 999,
              background: index % 3 === 0 ? palette.tealBright : "rgba(110, 184, 196, 0.5)",
              boxShadow: `0 0 18px ${palette.glow}`,
              opacity: 0.6,
              transform: `rotate(${rotate}deg)`,
            }}
          />
        );
      })}
    </>
  );
};
