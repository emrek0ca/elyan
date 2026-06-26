import React, {useMemo} from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {palette} from "../lib/palette";

type ParticleFieldProps = {
  count?: number;
  centerX?: number;
  centerY?: number;
  spread?: number;
  opacity?: number;
};

export const ParticleField: React.FC<ParticleFieldProps> = ({
  count = 36,
  centerX = 540,
  centerY = 960,
  spread = 480,
  opacity = 1,
}) => {
  const frame = useCurrentFrame();
  const particles = useMemo(
    () =>
      Array.from({length: count}, (_, index) => {
        const angle = (index / count) * Math.PI * 2;
        const radius = 120 + (index % 7) * (spread / 10);
        return {angle, radius, size: 4 + (index % 3) * 3, speed: 0.2 + (index % 5) * 0.04};
      }),
    [count, spread],
  );

  return (
    <>
      {particles.map((particle, index) => {
        const theta = particle.angle + frame * 0.002 * particle.speed;
        const x = centerX + Math.cos(theta) * particle.radius;
        const y = centerY + Math.sin(theta) * particle.radius * 0.66;
        const fade = interpolate(frame, [0, 40, 220], [0, 1, 0.6], {extrapolateRight: "clamp"});
        return (
          <div
            key={index}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: particle.size,
              height: particle.size,
              borderRadius: 999,
              background: palette.tealBright,
              boxShadow: `0 0 18px ${palette.glow}`,
              opacity: fade * opacity * (0.4 + ((index % 6) / 10)),
            }}
          />
        );
      })}
    </>
  );
};
