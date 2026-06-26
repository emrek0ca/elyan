import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {palette} from "../lib/palette";

const labels = ["Files", "Web", "Tasks", "Devices"];

export const DeviceCluster: React.FC = () => {
  const frame = useCurrentFrame();
  return (
    <>
      {labels.map((label, index) => {
        const xTargets = [120, 120, 700, 700];
        const yTargets = [480, 1110, 480, 1110];
        const x = interpolate(frame, [0, 180], [xTargets[index], 390 + (index % 2) * 210], {
          extrapolateRight: "clamp",
        });
        const y = interpolate(frame, [0, 180], [yTargets[index], 760 + Math.floor(index / 2) * 220], {
          extrapolateRight: "clamp",
        });
        const scale = interpolate(frame, [0, 180], [1, 0.84], {extrapolateRight: "clamp"});
        return (
          <div
            key={label}
            style={{
              position: "absolute",
              left: x,
              top: y,
              width: 260,
              height: 200,
              borderRadius: 32,
              border: `1px solid ${palette.line}`,
              background: "rgba(255,255,255,0.74)",
              boxShadow: "0 20px 50px rgba(10,20,24,0.08)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              transform: `scale(${scale})`,
            }}
          >
            <div
              style={{
                fontFamily: '"Grift Bold", system-ui, sans-serif',
                fontSize: 40,
                color: palette.shadow,
                letterSpacing: -1,
              }}
            >
              {label}
            </div>
          </div>
        );
      })}
    </>
  );
};
